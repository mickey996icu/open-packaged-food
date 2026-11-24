(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(root);
  } else {
    root.OPFScanner = factory(root);
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function (globalScope) {
  "use strict";

  const ZXING_FORMAT_MAP = [
    ["EAN_13", "ean_13"],
    ["EAN_8", "ean_8"],
    ["UPC_A", "upc_a"],
    ["UPC_E", "upc_e"],
    ["CODE_128", "code_128"],
    ["QR_CODE", "qr_code"],
    ["DATA_MATRIX", "data_matrix"],
  ];
  const BARCODE_FORMATS = ZXING_FORMAT_MAP.map((pair) => pair[1]);
  const OPF_ID_RE =
    /^opf:([a-z0-9]+(?:-[a-z0-9]+)*)\/([a-z0-9]+(?:-[a-z0-9]+)*)\/([a-z0-9]+(?:-[a-z0-9]+)*)$/i;
  const GTIN_LENGTHS = new Set([8, 12, 13, 14]);
  const MAX_ZXING_DIM = 1280;

  function isValidGs1CheckDigit(digits) {
    if (typeof digits !== "string" || !/^\d+$/.test(digits) || !GTIN_LENGTHS.has(digits.length)) {
      return false;
    }
    if (/^0+$/.test(digits)) return false;
    const body = digits.slice(0, -1);
    const check = Number(digits[digits.length - 1]);
    let total = 0;
    for (let i = 0; i < body.length; i += 1) {
      total += Number(body[body.length - 1 - i]) * (i % 2 === 0 ? 3 : 1);
    }
    return check === (10 - (total % 10)) % 10;
  }

  function buildGtinApiPath(gtin14) {
    return `v1/gtin/${gtin14.slice(1, 4)}/${gtin14.slice(4, 7)}/${gtin14}.json`;
  }

  function buildOpfApiPath(opfId) {
    const m = OPF_ID_RE.exec(opfId);
    return m ? `v1/opf/${m[1].toLowerCase()}/${m[2].toLowerCase()}/${m[3].toLowerCase()}.json` : null;
  }

  function classifyGtinCandidate(digits, rawText) {
    if (!isValidGs1CheckDigit(digits)) {
      return { kind: "invalid_gtin", raw: rawText, digits, valid: false };
    }
    const gtin14 = digits.padStart(14, "0");
    return {
      kind: "gtin",
      raw: rawText,
      digits,
      gtin14,
      id: `gtin:${gtin14}`,
      apiPath: buildGtinApiPath(gtin14),
      valid: true,
    };
  }

  function extractOpfFromUrl(url) {
    const cleanPath = url.pathname.replace(/\.(?:full\.)?json$/i, "");
    const m = /\/v1\/opf\/([a-z0-9-]+)\/([a-z0-9-]+)\/([a-z0-9-]+)$/i.exec(cleanPath);
    if (!m) return null;
    const id = `opf:${m[1].toLowerCase()}/${m[2].toLowerCase()}/${m[3].toLowerCase()}`;
    return OPF_ID_RE.test(id) ? id : null;
  }

  function extractDigitsFromUrl(url) {
    const dlMatch = /(?:^|\/)01\/(\d{8,14})(?:\/|$)/.exec(url.pathname);
    if (dlMatch) return dlMatch[1];
    const paramNames = ["gtin", "ean", "barcode", "code"];
    for (const [k, v] of url.searchParams.entries()) {
      if (!paramNames.includes(k.toLowerCase())) continue;
      const cleaned = v.trim().replace(/^gtin:/i, "");
      if (/^\d{8,14}$/.test(cleaned)) return cleaned;
    }
    const segments = url.pathname.split("/").filter(Boolean);
    for (let i = segments.length - 1; i >= 0; i -= 1) {
      const seg = segments[i].replace(/\.(?:full\.)?json$/i, "");
      if (/^\d{8,14}$/.test(seg)) return seg;
    }
    return null;
  }

  function parseScannedCode(rawText) {
    const text = String(rawText ?? "").trim();
    if (!text) return { kind: "empty", raw: "", valid: false };
    const opfMatch = OPF_ID_RE.exec(text);
    if (opfMatch) {
      const id = `opf:${opfMatch[1].toLowerCase()}/${opfMatch[2].toLowerCase()}/${opfMatch[3].toLowerCase()}`;
      return { kind: "opf", raw: text, id, apiPath: buildOpfApiPath(id), valid: true };
    }
    const gtinPrefMatch = /^gtin:\s*(\d+)$/i.exec(text);
    if (gtinPrefMatch) return classifyGtinCandidate(gtinPrefMatch[1], text);
    if (/^\d{8,14}$/.test(text)) return classifyGtinCandidate(text, text);
    if (/^https?:\/\//i.test(text)) {
      try {
        const url = new URL(text);
        const opfFromUrl = extractOpfFromUrl(url);
        if (opfFromUrl) {
          return { kind: "opf", raw: text, id: opfFromUrl, apiPath: buildOpfApiPath(opfFromUrl), valid: true };
        }
        const digits = extractDigitsFromUrl(url);
        if (digits) return classifyGtinCandidate(digits, text);
      } catch (_) {
        // Treat malformed URL as plain search text
      }
    }
    return { kind: "text", raw: text, query: text, valid: false };
  }

  function resolveZXingLib(explicitLib = null) {
    const candidate =
      explicitLib !== undefined && explicitLib !== null
        ? explicitLib
        : globalScope && globalScope.ZXing;
    return candidate &&
      typeof candidate === "object" &&
      typeof candidate.MultiFormatReader === "function"
      ? candidate
      : null;
  }

  function rgbaToGrayscale(rgba, width, height, reuseBuf = null) {
    const len = width * height;
    const out = reuseBuf && reuseBuf.length === len ? reuseBuf : new Uint8ClampedArray(len);
    for (let i = 0, p = 0; p < len; i += 4, p += 1) {
      const a = rgba[i + 3];
      if (a === 0) {
        out[p] = 255;
      } else {
        const lum = (306 * rgba[i] + 601 * rgba[i + 1] + 117 * rgba[i + 2] + 512) >> 10;
        out[p] = a === 255 ? lum : Math.round((lum * a + 255 * (255 - a)) / 255);
      }
    }
    return out;
  }

  function rotateGrayscale90CCW(gray, width, height) {
    const rotated = new Uint8ClampedArray(width * height);
    for (let y = 0; y < height; y += 1) {
      const srcRow = y * width;
      for (let x = 0; x < width; x += 1) {
        rotated[(width - 1 - x) * height + y] = gray[srcRow + x];
      }
    }
    return rotated;
  }

  function isZXingDecodeMiss(ZX, err) {
    if (!err) return true;
    if (typeof ZX.Exception === "function" && err instanceof ZX.Exception) return true;
    const name = String(err.name || "");
    const kind = typeof err.getKind === "function" ? String(err.getKind() || "") : "";
    const pat = /^(?:NotFound|Checksum|Format|Reader)Exception$/i;
    return pat.test(name) || pat.test(kind);
  }

  function tryDecodeSource(reader, ZX, source, useGlobalHistogram, reverseFormatMap) {
    const Binarizer =
      useGlobalHistogram && ZX.GlobalHistogramBinarizer
        ? ZX.GlobalHistogramBinarizer
        : ZX.HybridBinarizer;
    try {
      const result = reader.decodeWithState(new ZX.BinaryBitmap(new Binarizer(source)));
      const rawValue = result && typeof result.getText === "function" ? result.getText() : "";
      if (!rawValue) return null;
      const fmtVal = typeof result.getBarcodeFormat === "function" ? result.getBarcodeFormat() : null;
      return { rawValue, format: reverseFormatMap.get(fmtVal) || "unknown" };
    } catch (err) {
      if (isZXingDecodeMiss(ZX, err)) return null;
      throw err;
    } finally {
      if (typeof reader.reset === "function") reader.reset();
    }
  }

  function createZXingDetector(options = {}) {
    const ZX = resolveZXingLib(options.zxingLib);
    if (
      !ZX ||
      typeof ZX.MultiFormatReader !== "function" ||
      !ZX.DecodeHintType ||
      !ZX.BarcodeFormat ||
      typeof ZX.BinaryBitmap !== "function" ||
      typeof ZX.HybridBinarizer !== "function" ||
      (typeof ZX.RGBLuminanceSource !== "function" &&
        typeof ZX.HTMLCanvasElementLuminanceSource !== "function")
    ) {
      return null;
    }

    const hints = new Map();
    const reverseFormatMap = new Map();
    const formats = [];
    for (const [key, opfFormat] of ZXING_FORMAT_MAP) {
      const val = ZX.BarcodeFormat[key];
      if (val !== undefined) {
        formats.push(val);
        reverseFormatMap.set(val, opfFormat);
      }
    }
    if (formats.length) hints.set(ZX.DecodeHintType.POSSIBLE_FORMATS, formats);
    if (ZX.DecodeHintType.TRY_HARDER !== undefined) hints.set(ZX.DecodeHintType.TRY_HARDER, true);

    const reader = new ZX.MultiFormatReader();
    reader.setHints(hints);
    const doc = options.document || (typeof document !== "undefined" ? document : null);
    let scratchCanvas = null;
    let scratchCtx = null;
    let grayBuffer = null;

    function decodeGrayscale(gray, width, height, detectOpts = {}) {
      if (typeof ZX.RGBLuminanceSource !== "function") return [];
      const baseSource = new ZX.RGBLuminanceSource(gray, width, height);
      const thorough = Boolean(detectOpts.thorough);
      const frameIndex = Number(detectOpts.frameIndex || 0);
      const attempts = [{ src: baseSource, global: false }];
      if (thorough && ZX.GlobalHistogramBinarizer) attempts.push({ src: baseSource, global: true });
      if ((thorough || frameIndex % 3 === 1) && typeof baseSource.invert === "function") {
        attempts.push({ src: baseSource.invert(), global: false });
      }
      if (thorough || frameIndex % 2 === 1) {
        const rotSource = new ZX.RGBLuminanceSource(rotateGrayscale90CCW(gray, width, height), height, width);
        attempts.push({ src: rotSource, global: false });
        if (thorough && typeof rotSource.invert === "function") {
          attempts.push({ src: rotSource.invert(), global: false });
        }
      }
      for (const attempt of attempts) {
        const hit = tryDecodeSource(reader, ZX, attempt.src, attempt.global, reverseFormatMap);
        if (hit) return [hit];
      }
      return [];
    }

    function ensureCanvas(width, height) {
      if (!doc || typeof doc.createElement !== "function") return null;
      if (!scratchCanvas) {
        scratchCanvas = doc.createElement("canvas");
        scratchCtx = scratchCanvas.getContext("2d", { willReadFrequently: true });
      }
      if (!scratchCtx) return null;
      if (scratchCanvas.width !== width) scratchCanvas.width = width;
      if (scratchCanvas.height !== height) scratchCanvas.height = height;
      return { canvas: scratchCanvas, ctx: scratchCtx };
    }

    return {
      engine: "zxing",
      detect(source, detectOpts = {}) {
        if (!source) return [];
        if (source.data && Number(source.width) > 0 && Number(source.height) > 0) {
          const w = Number(source.width);
          const h = Number(source.height);
          const len = w * h;
          if (source.data.length === len) return decodeGrayscale(source.data, w, h, detectOpts);
          if (source.data.length === len * 4) {
            grayBuffer = rgbaToGrayscale(source.data, w, h, grayBuffer);
            return decodeGrayscale(grayBuffer, w, h, detectOpts);
          }
          return [];
        }

        const width = Number(source.videoWidth || source.naturalWidth || source.width || 0);
        const height = Number(source.videoHeight || source.naturalHeight || source.height || 0);
        if (!width || !height) return [];
        const maxDim = Number(detectOpts.maxDim || MAX_ZXING_DIM);
        const scale = Math.max(width, height) > maxDim ? maxDim / Math.max(width, height) : 1;
        const targetW = Math.max(1, Math.round(width * scale));
        const targetH = Math.max(1, Math.round(height * scale));
        const surface = ensureCanvas(targetW, targetH);
        if (!surface) return [];

        surface.ctx.fillStyle = "#ffffff";
        surface.ctx.fillRect(0, 0, targetW, targetH);
        surface.ctx.drawImage(source, 0, 0, targetW, targetH);

        if (typeof ZX.RGBLuminanceSource === "function") {
          const imgData = surface.ctx.getImageData(0, 0, targetW, targetH);
          grayBuffer = rgbaToGrayscale(imgData.data, targetW, targetH, grayBuffer);
          return decodeGrayscale(grayBuffer, targetW, targetH, detectOpts);
        }
        const hit = tryDecodeSource(
          reader,
          ZX,
          new ZX.HTMLCanvasElementLuminanceSource(surface.canvas),
          false,
          reverseFormatMap
        );
        return hit ? [hit] : [];
      },
      reset() {
        if (typeof reader.reset === "function") reader.reset();
        grayBuffer = null;
      },
    };
  }

  async function createNativeBarcodeDetector(win) {
    if (!win || typeof win.BarcodeDetector !== "function") {
      return { detector: null, partialCoverage: false };
    }
    const Detector = win.BarcodeDetector;
    try {
      if (typeof Detector.getSupportedFormats === "function") {
        const supported = await Detector.getSupportedFormats();
        if (!Array.isArray(supported)) return { detector: null, partialCoverage: false };
        const chosen = BARCODE_FORMATS.filter((fmt) => supported.includes(fmt));
        if (!chosen.length) return { detector: null, partialCoverage: false };
        const partialCoverage = !chosen.includes("ean_13") || !chosen.includes("qr_code");
        return { detector: new Detector({ formats: chosen }), partialCoverage };
      }
      return { detector: new Detector({ formats: BARCODE_FORMATS }), partialCoverage: false };
    } catch (_) {
      try {
        return { detector: new Detector(), partialCoverage: false };
      } catch (__) {
        return { detector: null, partialCoverage: false };
      }
    }
  }

  async function createBarcodeDetector(options = {}) {
    const win = options.window || (typeof window !== "undefined" ? window : globalScope);
    const nativeInfo = await createNativeBarcodeDetector(win);
    const nativeDetector = nativeInfo.detector;
    const zxingDetector = createZXingDetector(options);
    if (!nativeDetector && !zxingDetector) return null;

    let nativeFailed = !nativeDetector;
    const engine =
      nativeDetector && zxingDetector ? "native+zxing" : nativeDetector ? "native" : "zxing";

    return {
      engine,
      hasNative: Boolean(nativeDetector),
      hasZXing: Boolean(zxingDetector),
      isNativeActive: () => Boolean(nativeDetector) && !nativeFailed,
      async detect(source, detectOpts = {}) {
        if (nativeDetector && !nativeFailed) {
          try {
            const nativeCodes = await nativeDetector.detect(source);
            if (Array.isArray(nativeCodes) && nativeCodes.some((c) => c && c.rawValue)) {
              return nativeCodes;
            }
          } catch (err) {
            nativeFailed = true;
            if (!zxingDetector) throw err;
          }
          if (!zxingDetector) return [];
          const shouldFallback =
            nativeFailed ||
            Boolean(detectOpts.thorough) ||
            (nativeInfo.partialCoverage && Number(detectOpts.frameIndex || 0) % 2 === 1);
          if (!shouldFallback) return [];
        }
        return zxingDetector ? zxingDetector.detect(source, detectOpts) : [];
      },
      reset() {
        if (zxingDetector) zxingDetector.reset();
      },
    };
  }

  function hasAvailableDetector(options = {}) {
    const win = options.window || (typeof window !== "undefined" ? window : globalScope);
    return Boolean(
      (win && typeof win.BarcodeDetector === "function") || resolveZXingLib(options.zxingLib)
    );
  }

  function createScannerController(deps = {}) {
    const doc = deps.document || (typeof document !== "undefined" ? document : null);
    const win = deps.window || (typeof window !== "undefined" ? window : globalScope);
    const nav = deps.navigator || (typeof navigator !== "undefined" ? navigator : null);
    const t = deps.t || ((key) => key);
    const esc = deps.esc || ((v) => String(v ?? ""));
    const rel = deps.rel || ((p) => String(p).replace(/^\//, ""));
    const fetchImpl = deps.fetch || (typeof fetch === "function" ? fetch : null);
    const copyTextWithFeedback = deps.copyTextWithFeedback || (() => {});
    const getCatalog = deps.getCatalog || (() => []);
    const applySearchQuery = deps.applySearchQuery || (() => {});
    const selectCatalogItem = deps.selectCatalogItem || (async () => {});
    const $ = (sel) => (doc ? doc.querySelector(sel) : null);

    const state = {
      stream: null,
      rafId: null,
      timerId: null,
      token: 0,
      frameIndex: 0,
      detectBusy: false,
      detector: null,
      lastFocused: null,
    };

    function updateChromeText() {
      const toggleBtn = $("#scan-camera-toggle");
      if (!toggleBtn) return;
      const active = Boolean(state.stream);
      toggleBtn.textContent = t(active ? "scanner.stopCameraBtn" : "scanner.startCameraBtn");
      toggleBtn.setAttribute("aria-pressed", String(active));
    }

    function setStatus(message, tone = "info") {
      const el = $("#scan-status");
      if (!el) return;
      el.hidden = !message;
      el.textContent = message || "";
      if (message) el.dataset.tone = tone;
      else delete el.dataset.tone;
    }

    function setResult(html = "") {
      const el = $("#scan-result");
      if (!el) return;
      el.hidden = !html;
      el.innerHTML = html || "";
    }

    function stopTracksOnStream(stream) {
      if (!stream || typeof stream.getTracks !== "function") return;
      for (const track of stream.getTracks()) {
        try {
          track.stop();
        } catch (_) {
          // Ignore already-stopped track errors
        }
      }
    }

    function stopCamera() {
      state.token += 1;
      state.detectBusy = false;
      if (state.rafId !== null && typeof cancelAnimationFrame === "function") cancelAnimationFrame(state.rafId);
      state.rafId = null;
      if (state.timerId !== null) clearTimeout(state.timerId);
      state.timerId = null;

      const prevStream = state.stream;
      stopTracksOnStream(prevStream);
      state.stream = null;
      if (state.detector && typeof state.detector.reset === "function") state.detector.reset();

      const videoEl = $("#scan-video");
      if (videoEl) {
        if (videoEl.srcObject && videoEl.srcObject !== prevStream) stopTracksOnStream(videoEl.srcObject);
        if (typeof videoEl.pause === "function") videoEl.pause();
        videoEl.srcObject = null;
      }
      const viewport = $("#scan-viewport");
      if (viewport) viewport.dataset.active = "false";
      updateChromeText();
    }

    async function ensureDetector() {
      if (!state.detector) {
        state.detector = await createBarcodeDetector({ window: win, document: doc, zxingLib: deps.zxingLib });
      }
      return state.detector;
    }

    function renderCodeResultCard(titleText, descText, codeText) {
      setStatus("", "info");
      setResult(
        `<strong>${esc(titleText)}</strong><p>${esc(descText)}</p>` +
          `<div class="scan-result-code-row"><code class="scan-code-pill mono">${esc(codeText)}</code>` +
          `<button type="button" class="chip copy-scan-id-btn" data-copy-text="${esc(codeText)}">${esc(t("scanner.copyCodeBtn"))}</button></div>`
      );
    }

    async function processPayload(rawText) {
      const parsed = parseScannedCode(rawText);
      if (parsed.kind === "empty") return setStatus(t("scanner.emptyInput"), "warn");
      if (parsed.kind === "invalid_gtin") {
        setStatus(t("scanner.invalidCheckDigit", { digits: parsed.digits }), "error");
        return setResult("");
      }
      if (parsed.kind === "text") {
        applySearchQuery(parsed.query, true);
        setStatus(t("scanner.plainTextNotice", { text: parsed.query }), "warn");
        return setResult("");
      }

      applySearchQuery(parsed.id, false);
      const matchItem = (item) =>
        item.id === parsed.id || (Array.isArray(item.aliases) && item.aliases.includes(parsed.id));
      const exactHit = getCatalog().find(matchItem);
      if (exactHit) {
        setStatus(t("scanner.hitFound", { id: parsed.id }), "info");
        setResult("");
        closeModal();
        await selectCatalogItem(exactHit, true);
        return;
      }

      setStatus(t("scanner.lookupChecking", { id: parsed.id }), "info");
      if (fetchImpl) {
        try {
          const resp = await fetchImpl(rel(parsed.apiPath));
          if (resp.ok) {
            const payload = await resp.json();
            const targetId = payload && payload.id ? payload.id : parsed.id;
            const catalogMatch = getCatalog().find((item) => item.id === targetId);
            if (catalogMatch) {
              closeModal();
              await selectCatalogItem(catalogMatch, true);
              return;
            }
            return renderCodeResultCard(
              t("scanner.directHitTitle", { id: targetId }),
              t("scanner.directHitDesc", { path: parsed.apiPath }),
              targetId
            );
          }
        } catch (_) {
          // Treat network/404 failure uniformly as unindexed fallback
        }
      }
      renderCodeResultCard(
        t("scanner.notFoundTitle", { id: parsed.id }),
        t("scanner.notFoundDesc", { path: parsed.apiPath }),
        parsed.id
      );
    }

    function scheduleNextVideoScan(detector, videoEl, sessionToken) {
      if (sessionToken !== state.token) return;
      const modal = $("#scan-modal");
      if (!modal || modal.hidden || !state.stream) return;
      const scheduleFrame =
        typeof requestAnimationFrame === "function" ? requestAnimationFrame : (fn) => setTimeout(fn, 0);

      state.timerId = setTimeout(() => {
        if (sessionToken !== state.token) return;
        state.rafId = scheduleFrame(async () => {
          if (sessionToken !== state.token || state.detectBusy) return;
          if (videoEl.readyState >= 2) {
            state.detectBusy = true;
            const frameIndex = state.frameIndex++;
            try {
              const codes = await detector.detect(videoEl, { thorough: false, frameIndex });
              if (sessionToken !== state.token) return;
              const hit = Array.isArray(codes) ? codes.find((c) => c && c.rawValue) : null;
              if (hit) {
                stopCamera();
                await processPayload(hit.rawValue);
                return;
              }
            } catch (err) {
              if (sessionToken !== state.token) return;
              stopCamera();
              setStatus(t("scanner.cameraError", { reason: err && err.message ? err.message : "detect" }), "error");
              return;
            } finally {
              state.detectBusy = false;
            }
          }
          scheduleNextVideoScan(detector, videoEl, sessionToken);
        });
      }, 180);
    }

    async function startCamera() {
      stopCamera();
      const sessionToken = state.token;
      if (win && win.isSecureContext === false) return setStatus(t("scanner.insecureContext"), "warn");
      const detector = await ensureDetector();
      if (!detector) return setStatus(t("scanner.unsupportedDetector"), "warn");
      if (!nav || !nav.mediaDevices || typeof nav.mediaDevices.getUserMedia !== "function") {
        return setStatus(t("scanner.cameraPermissionDenied"), "error");
      }

      try {
        const stream = await nav.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" } },
          audio: false,
        });
        const modal = $("#scan-modal");
        if (sessionToken !== state.token || !modal || modal.hidden) {
          stopTracksOnStream(stream);
          return;
        }
        state.stream = stream;
        state.frameIndex = 0;
        const videoEl = $("#scan-video");
        const viewport = $("#scan-viewport");
        if (videoEl) {
          videoEl.srcObject = stream;
          if (typeof videoEl.play === "function") await videoEl.play();
        }
        if (viewport) viewport.dataset.active = "true";
        updateChromeText();
        setStatus(t("scanner.cameraLive"), "info");
        if (videoEl) scheduleNextVideoScan(detector, videoEl, sessionToken);
      } catch (err) {
        stopCamera();
        const name = err && err.name ? err.name : "";
        const denied = name === "NotAllowedError" || name === "PermissionDeniedError" || name === "NotFoundError";
        setStatus(
          denied
            ? t("scanner.cameraPermissionDenied")
            : t("scanner.cameraError", { reason: (err && err.message) || name || "error" }),
          "error"
        );
      }
    }

    async function loadImageSource(file) {
      if (typeof createImageBitmap === "function") {
        try {
          return { source: await createImageBitmap(file), objectUrl: null };
        } catch (_) {
          // Fall through to HTMLImageElement loader if createImageBitmap rejects
        }
      }
      if (typeof URL !== "undefined" && typeof URL.createObjectURL === "function") {
        const objectUrl = URL.createObjectURL(file);
        const source = await new Promise((resolve, reject) => {
          const img = new Image();
          img.onload = () => resolve(img);
          img.onerror = () => reject(new Error("image load failed"));
          img.src = objectUrl;
        });
        return { source, objectUrl };
      }
      throw new Error("image decoding unsupported");
    }

    async function handleImageFile(file) {
      if (!file) return;
      stopCamera();
      setResult("");
      const detector = await ensureDetector();
      if (!detector) return setStatus(t("scanner.unsupportedDetector"), "warn");
      setStatus(t("scanner.scanningImage"), "info");
      let loaded = null;
      try {
        loaded = await loadImageSource(file);
        const codes = await detector.detect(loaded.source, { thorough: true });
        const hit = Array.isArray(codes) ? codes.find((c) => c && c.rawValue) : null;
        if (!hit) return setStatus(t("scanner.noBarcodeInImage"), "warn");
        await processPayload(hit.rawValue);
      } catch (err) {
        setStatus(t("scanner.imageError", { reason: (err && err.message) || "error" }), "error");
      } finally {
        if (loaded && loaded.source && typeof loaded.source.close === "function") loaded.source.close();
        if (loaded && loaded.objectUrl && typeof URL !== "undefined" && typeof URL.revokeObjectURL === "function") {
          URL.revokeObjectURL(loaded.objectUrl);
        }
      }
    }

    function openModal() {
      const modal = $("#scan-modal");
      if (!modal) return;
      state.lastFocused = doc ? doc.activeElement : null;
      modal.hidden = false;
      setStatus("", "info");
      setResult("");
      updateChromeText();
      if (win && win.isSecureContext === false) {
        setStatus(t("scanner.insecureContext"), "warn");
      } else if (!hasAvailableDetector({ window: win, zxingLib: deps.zxingLib })) {
        setStatus(t("scanner.unsupportedDetector"), "warn");
      }
      const manualInput = $("#scan-manual-input");
      if (manualInput && typeof manualInput.focus === "function") manualInput.focus();
    }

    function closeModal() {
      stopCamera();
      const modal = $("#scan-modal");
      if (modal) modal.hidden = true;
      if (state.lastFocused && typeof state.lastFocused.focus === "function") state.lastFocused.focus();
      state.lastFocused = null;
    }

    function init() {
      const bind = (sel, evt, handler) => {
        const el = $(sel);
        if (el) el.addEventListener(evt, handler);
      };
      bind("#scan-btn", "click", openModal);
      bind("#scan-close-btn", "click", closeModal);
      bind("#scan-backdrop", "click", closeModal);
      bind("#scan-camera-toggle", "click", () => (state.stream ? stopCamera() : startCamera()));
      bind(".scan-file-label", "keydown", (e) => {
        const fileInput = $("#scan-file");
        if (fileInput && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          fileInput.click();
        }
      });
      bind("#scan-file", "change", async (e) => {
        await handleImageFile(e.target.files && e.target.files[0]);
        e.target.value = "";
      });
      bind("#scan-manual-form", "submit", async (e) => {
        e.preventDefault();
        stopCamera();
        const inputEl = $("#scan-manual-input");
        await processPayload(inputEl ? inputEl.value : "");
      });
      bind("#scan-result", "click", (e) => {
        const copyBtn = e.target.closest(".copy-scan-id-btn");
        if (copyBtn && copyBtn.dataset.copyText) {
          copyTextWithFeedback(copyBtn, copyBtn.dataset.copyText, t("scanner.copyCodeBtn"));
        }
      });
      if (doc && typeof doc.addEventListener === "function") {
        doc.addEventListener("visibilitychange", () => {
          if (doc.hidden) stopCamera();
        });
      }
      if (win && typeof win.addEventListener === "function") win.addEventListener("pagehide", stopCamera);
    }

    return {
      init,
      openModal,
      closeModal,
      stopCamera,
      startCamera,
      handleImageFile,
      processPayload,
      updateChromeText,
      getState: () => state,
    };
  }

  return {
    BARCODE_FORMATS,
    isValidGs1CheckDigit,
    buildGtinApiPath,
    buildOpfApiPath,
    parseScannedCode,
    rgbaToGrayscale,
    rotateGrayscale90CCW,
    resolveZXingLib,
    createZXingDetector,
    createBarcodeDetector,
    hasAvailableDetector,
    createScannerController,
  };
});
