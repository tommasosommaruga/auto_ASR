/* Browser mic chain, live record path, and signal-plane drawing. */

(function (global) {
  const STORAGE_KEY = "autoAsr.mixer.v2";

  const PRESETS = {
    off: {
      gain: 1,
      autoGain: false,
      highpass: 0,
      lowpass: 0,
      gate: 0,
      compression: 0,
      notch: "off",
      agcTarget: 0.25,
      agcSpeed: 0.08,
    },
    voice: {
      gain: 1.2,
      autoGain: true,
      highpass: 70,
      lowpass: 0,
      gate: 0,
      compression: 0.15,
      notch: "off",
      agcTarget: 0.22,
      agcSpeed: 0.06,
    },
    speaker: {
      gain: 2.5,
      autoGain: true,
      highpass: 90,
      lowpass: 9000,
      gate: 0,
      compression: 0.25,
      notch: "off",
      agcTarget: 0.28,
      agcSpeed: 0.1,
    },
  };

  function defaults() {
    return { preset: "off", ...PRESETS.off };
  }

  function loadSettings() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return defaults();
      return { ...defaults(), ...JSON.parse(raw) };
    } catch (_error) {
      return defaults();
    }
  }

  function saveSettings(settings) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  }

  function applyPreset(name, current) {
    const base = PRESETS[name];
    if (!base) return { ...current, preset: "custom" };
    return { ...current, ...base, preset: name };
  }

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function configureCompressor(node, amount) {
    const strength = clamp(Number(amount) || 0, 0, 1);
    if (strength <= 0) {
      node.threshold.value = 0;
      node.knee.value = 0;
      node.ratio.value = 1;
      node.attack.value = 0.003;
      node.release.value = 0.1;
      return;
    }
    node.threshold.value = -12 - strength * 18;
    node.knee.value = 8 + strength * 8;
    node.ratio.value = 1 + strength * 5;
    node.attack.value = 0.01;
    node.release.value = 0.18;
  }

  function configureNotch(node, mode) {
    if (mode === "50" || mode === "60") {
      node.type = "notch";
      node.frequency.value = mode === "60" ? 60 : 50;
      node.Q.value = 30;
      return;
    }
    node.type = "allpass";
    node.frequency.value = 1000;
    node.Q.value = 0.7;
  }

  function createGraph(context, settings) {
    const input = context.createGain();
    input.gain.value = 1;

    const highpass = context.createBiquadFilter();
    highpass.type = "highpass";
    highpass.frequency.value = settings.highpass > 0 ? settings.highpass : 20;
    highpass.Q.value = 0.707;

    const lowpass = context.createBiquadFilter();
    lowpass.type = "lowpass";
    lowpass.frequency.value = settings.lowpass > 0 ? settings.lowpass : 20000;
    lowpass.Q.value = 0.707;

    const notch = context.createBiquadFilter();
    configureNotch(notch, settings.notch);

    const compressor = context.createDynamicsCompressor();
    configureCompressor(compressor, settings.compression);

    const sense = context.createAnalyser();
    sense.fftSize = 2048;
    sense.smoothingTimeConstant = 0.7;

    const gate = context.createGain();
    gate.gain.value = 1;

    const gain = context.createGain();
    gain.gain.value = clamp(Number(settings.gain) || 1, 0.05, 20);

    const analyser = context.createAnalyser();
    analyser.fftSize = 2048;
    analyser.smoothingTimeConstant = 0.75;

    const output = context.createGain();
    output.gain.value = 1;

    input.connect(highpass);
    highpass.connect(lowpass);
    lowpass.connect(notch);
    notch.connect(compressor);
    compressor.connect(sense);
    sense.connect(gate);
    gate.connect(gain);
    gain.connect(analyser);
    analyser.connect(output);

    return {
      input,
      highpass,
      lowpass,
      notch,
      compressor,
      sense,
      gate,
      gain,
      analyser,
      output,
      settings: { ...settings },
    };
  }

  function updateGraph(graph, settings) {
    graph.settings = { ...settings };
    graph.highpass.frequency.value = settings.highpass > 0 ? settings.highpass : 20;
    graph.lowpass.frequency.value = settings.lowpass > 0 ? settings.lowpass : 20000;
    configureNotch(graph.notch, settings.notch);
    configureCompressor(graph.compressor, settings.compression);
    if (!settings.autoGain) {
      graph.gain.gain.value = clamp(Number(settings.gain) || 1, 0.05, 20);
    }
    if (!(Number(settings.gate) > 0)) graph.gate.gain.value = 1;
  }

  function readLevel(analyser) {
    const data = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(data);
    let sum = 0;
    let peak = 0;
    for (let i = 0; i < data.length; i += 1) {
      const sample = data[i];
      sum += sample * sample;
      peak = Math.max(peak, Math.abs(sample));
    }
    return { rms: Math.sqrt(sum / data.length), peak, data };
  }

  function tickAgc(graph) {
    if (!graph.settings.autoGain) return;
    const { rms } = readLevel(graph.sense);
    if (rms < 0.001) return;
    const target = clamp(Number(graph.settings.agcTarget) || 0.25, 0.05, 0.5);
    const speed = clamp(Number(graph.settings.agcSpeed) || 0.08, 0.02, 0.3);
    const current = graph.gain.gain.value;
    const desired = clamp(current * (target / Math.max(rms, 0.0001)), 0.5, 12);
    graph.gain.gain.value = current + (desired - current) * speed;
  }

  function tickGate(graph) {
    const floor = Number(graph.settings.gate) || 0;
    if (floor <= 0) {
      graph.gate.gain.value = 1;
      return;
    }
    const { rms } = readLevel(graph.sense);
    graph.gate.gain.value = rms >= floor ? 1 : 0.15;
  }

  async function processBuffer(audioBuffer, settings) {
    const offline = new OfflineAudioContext(1, audioBuffer.length, audioBuffer.sampleRate);
    const source = offline.createBufferSource();
    source.buffer = audioBuffer;
    const graph = createGraph(offline, settings);
    source.connect(graph.input);
    graph.output.connect(offline.destination);
    if (settings.autoGain) {
      const peak = peakOf(audioBuffer);
      const target = clamp(Number(settings.agcTarget) || 0.25, 0.05, 0.5);
      const boost = peak > 0 ? clamp(target / peak, 0.8, 16) : 1;
      graph.gain.gain.value = clamp((Number(settings.gain) || 1) * boost, 0.5, 16);
    }
    graph.gate.gain.value = 1;
    source.start(0);
    return offline.startRendering();
  }

  function peakOf(buffer) {
    let peak = 0;
    for (let c = 0; c < buffer.numberOfChannels; c += 1) {
      const data = buffer.getChannelData(c);
      for (let i = 0; i < data.length; i += 1) peak = Math.max(peak, Math.abs(data[i]));
    }
    return peak;
  }

  function bufferToWavBlob(buffer) {
    const samples = buffer.numberOfChannels === 1
      ? buffer.getChannelData(0)
      : mixToMono(buffer);
    const rate = buffer.sampleRate;
    const bytes = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(bytes);
    writeString(view, 0, "RIFF");
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(view, 8, "WAVE");
    writeString(view, 12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, rate, true);
    view.setUint32(28, rate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(view, 36, "data");
    view.setUint32(40, samples.length * 2, true);
    let offset = 44;
    for (let i = 0; i < samples.length; i += 1) {
      const sample = clamp(samples[i], -1, 1);
      view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
      offset += 2;
    }
    return new Blob([bytes], { type: "audio/wav" });
  }

  function mixToMono(buffer) {
    const length = buffer.length;
    const mono = new Float32Array(length);
    const channels = buffer.numberOfChannels;
    for (let c = 0; c < channels; c += 1) {
      const data = buffer.getChannelData(c);
      for (let i = 0; i < length; i += 1) mono[i] += data[i] / channels;
    }
    return mono;
  }

  function writeString(view, offset, text) {
    for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i));
  }

  /** Always records the processed chain so live mixer changes land in the file. */
  function createLiveSession(stream, settings, options = {}) {
    const context = new AudioContext();
    const source = context.createMediaStreamSource(stream);

    const rawAnalyser = context.createAnalyser();
    rawAnalyser.fftSize = 2048;
    rawAnalyser.smoothingTimeConstant = 0.65;

    const graph = createGraph(context, settings);
    source.connect(rawAnalyser);
    source.connect(graph.input);

    const destination = context.createMediaStreamDestination();
    graph.output.connect(destination);

    let monitor = null;
    if (options.monitor) {
      monitor = context.createGain();
      monitor.gain.value = 0.7;
      graph.output.connect(monitor);
      monitor.connect(context.destination);
    }

    let raf = 0;
    const onFrame = typeof options.onFrame === "function" ? options.onFrame : null;
    const onLevel = typeof options.onLevel === "function" ? options.onLevel : null;

    function loop() {
      tickGate(graph);
      tickAgc(graph);
      const raw = readLevel(rawAnalyser);
      const processed = readLevel(graph.analyser);
      if (onLevel) onLevel(processed, graph.gain.gain.value);
      if (onFrame) {
        onFrame({
          raw: raw.data,
          processed: processed.data,
          rawRms: raw.rms,
          processedRms: processed.rms,
          gain: graph.gain.gain.value,
          gate: graph.gate.gain.value,
        });
      }
      raf = requestAnimationFrame(loop);
    }
    loop();

    return {
      context,
      graph,
      stream: destination.stream,
      update(next) {
        updateGraph(graph, next);
      },
      setMonitor(enabled) {
        if (enabled && !monitor) {
          monitor = context.createGain();
          monitor.gain.value = 0.7;
          graph.output.connect(monitor);
          monitor.connect(context.destination);
        }
        if (monitor) monitor.gain.value = enabled ? 0.7 : 0;
      },
      async stop() {
        cancelAnimationFrame(raf);
        try {
          await context.close();
        } catch (_error) {
          // already closed
        }
      },
    };
  }

  /**
   * Data-science style scope: raw fill, suppression overlay, processed stroke.
   * Draws into a canvas that should be CSS-sized; DPR is handled here.
   */
  function createSignalPlane(canvas) {
    const ctx = canvas.getContext("2d");
    let hover = null;
    let lastFrame = null;

    canvas.addEventListener("pointermove", (event) => {
      const rect = canvas.getBoundingClientRect();
      hover = {
        x: (event.clientX - rect.left) / rect.width,
        y: (event.clientY - rect.top) / rect.height,
      };
      if (lastFrame) draw(lastFrame);
    });
    canvas.addEventListener("pointerleave", () => {
      hover = null;
      if (lastFrame) draw(lastFrame);
    });

    function resize() {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      // Hidden panels report 0×0; keep prior bitmap until the view is laid out.
      if (rect.width < 2 || rect.height < 2) {
        return {
          width: Math.max(1, canvas.width),
          height: Math.max(1, canvas.height),
          dpr,
          skipped: true,
        };
      }
      const width = Math.max(1, Math.floor(rect.width * dpr));
      const height = Math.max(1, Math.floor(rect.height * dpr));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      return { width, height, dpr, skipped: false };
    }

    function draw(frame) {
      if (frame) lastFrame = frame;
      const { width, height, skipped } = resize();
      if (skipped && (!canvas.width || !canvas.height)) return;
      const raw = frame && frame.raw;
      const processed = frame && frame.processed;
      ctx.clearRect(0, 0, width, height);

      // Plot background
      ctx.fillStyle = "#1c1915";
      ctx.fillRect(0, 0, width, height);

      // Grid
      ctx.strokeStyle = "rgba(243,239,230,0.08)";
      ctx.lineWidth = 1;
      for (let i = 1; i < 4; i += 1) {
        const y = (height * i) / 4;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }
      for (let i = 1; i < 8; i += 1) {
        const x = (width * i) / 8;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
      }

      // Zero line
      ctx.strokeStyle = "rgba(243,239,230,0.22)";
      ctx.beginPath();
      ctx.moveTo(0, height / 2);
      ctx.lineTo(width, height / 2);
      ctx.stroke();

      if (!raw || !processed || !raw.length) {
        paintLegend(ctx, width, height, null);
        return;
      }

      const mid = height / 2;
      const amp = height * 0.42;
      const step = Math.max(1, Math.floor(raw.length / width));
      const rawEnv = new Float32Array(width);
      const procEnv = new Float32Array(width);
      // Peak per column so live frames read as a moving meter, not a thin bipolar line.
      let maxPeak = 0;
      for (let x = 0; x < width; x += 1) {
        const start = Math.min(raw.length - 1, x * step);
        const end = Math.min(raw.length, start + step);
        let rawPeak = 0;
        let procPeak = 0;
        for (let i = start; i < end; i += 1) {
          rawPeak = Math.max(rawPeak, Math.abs(raw[i]));
          const pi = Math.min(processed.length - 1, i);
          procPeak = Math.max(procPeak, Math.abs(processed[pi]));
        }
        rawEnv[x] = rawPeak;
        procEnv[x] = procPeak;
        maxPeak = Math.max(maxPeak, rawPeak, procPeak);
      }
      // Quiet clips otherwise look like an empty grey canvas.
      const boost = maxPeak > 0.0005 && maxPeak < 0.2 ? 0.85 / maxPeak : 1;
      if (boost !== 1) {
        for (let x = 0; x < width; x += 1) {
          rawEnv[x] = Math.min(1, rawEnv[x] * boost);
          procEnv[x] = Math.min(1, procEnv[x] * boost);
        }
      }

      function fillSymmetric(envelope, style) {
        ctx.beginPath();
        ctx.moveTo(0, mid);
        for (let x = 0; x < width; x += 1) {
          ctx.lineTo(x, mid - envelope[x] * amp);
        }
        for (let x = width - 1; x >= 0; x -= 1) {
          ctx.lineTo(x, mid + envelope[x] * amp);
        }
        ctx.closePath();
        ctx.fillStyle = style;
        ctx.fill();
      }

      // Raw (grey) — full symmetric envelope. Old draw used 0.15× under the mid
      // line, so grey vanished under the full-scale green stroke.
      fillSymmetric(rawEnv, "rgba(156, 145, 128, 0.55)");

      // Removed (coral) — band where filters/gate cut level (|raw| > |processed|).
      ctx.beginPath();
      ctx.moveTo(0, mid - rawEnv[0] * amp);
      for (let x = 0; x < width; x += 1) {
        ctx.lineTo(x, mid - rawEnv[x] * amp);
      }
      for (let x = width - 1; x >= 0; x -= 1) {
        const kept = Math.min(rawEnv[x], procEnv[x]);
        ctx.lineTo(x, mid - kept * amp);
      }
      ctx.closePath();
      ctx.fillStyle = "rgba(196, 92, 62, 0.55)";
      ctx.fill();

      ctx.beginPath();
      ctx.moveTo(0, mid + Math.min(rawEnv[0], procEnv[0]) * amp);
      for (let x = 0; x < width; x += 1) {
        const kept = Math.min(rawEnv[x], procEnv[x]);
        ctx.lineTo(x, mid + kept * amp);
      }
      for (let x = width - 1; x >= 0; x -= 1) {
        ctx.lineTo(x, mid + rawEnv[x] * amp);
      }
      ctx.closePath();
      ctx.fillStyle = "rgba(196, 92, 62, 0.4)";
      ctx.fill();

      // Processed / recorded (green) — fill + stroke at the same scale as raw.
      fillSymmetric(procEnv, "rgba(61, 186, 140, 0.28)");
      ctx.beginPath();
      for (let x = 0; x < width; x += 1) {
        const y = mid - procEnv[x] * amp;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      for (let x = width - 1; x >= 0; x -= 1) {
        ctx.lineTo(x, mid + procEnv[x] * amp);
      }
      ctx.closePath();
      ctx.strokeStyle = "#3dba8c";
      ctx.lineWidth = Math.max(1.5, width / 500);
      ctx.stroke();

      // Raw outline so grey stays readable when gain boosts past the input.
      ctx.beginPath();
      for (let x = 0; x < width; x += 1) {
        const y = mid - rawEnv[x] * amp;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = "rgba(196, 186, 168, 0.9)";
      ctx.lineWidth = Math.max(1, width / 700);
      ctx.stroke();

      // Hover readout
      if (hover) {
        const hx = clamp(hover.x, 0, 1) * (width - 1);
        const xi = Math.min(width - 1, Math.floor(hx));
        const rawV = rawEnv[xi];
        const procV = procEnv[xi];
        const removed = Math.max(0, rawV - procV);
        ctx.strokeStyle = "rgba(243,239,230,0.55)";
        ctx.beginPath();
        ctx.moveTo(hx, 0);
        ctx.lineTo(hx, height);
        ctx.stroke();
        paintLegend(ctx, width, height, {
          raw: rawV,
          processed: procV,
          removed,
          rmsIn: frame.rawRms,
          rmsOut: frame.processedRms,
          gain: frame.gain,
          gate: frame.gate,
        });
      } else {
        paintLegend(ctx, width, height, {
          rmsIn: frame.rawRms,
          rmsOut: frame.processedRms,
          gain: frame.gain,
          gate: frame.gate,
        });
      }
    }

    function idle() {
      lastFrame = null;
      draw(null);
    }

    function redraw() {
      draw(lastFrame);
    }

    return { draw, idle, redraw };
  }

  /** Peak envelope for offline / whole-file meters (single samples look empty). */
  function peakEnvelope(channelData, points) {
    const count = Math.max(1, points | 0);
    const out = new Float32Array(count);
    if (!channelData || !channelData.length) return out;
    const block = Math.max(1, Math.floor(channelData.length / count));
    for (let i = 0; i < count; i += 1) {
      const start = i * block;
      const end = Math.min(channelData.length, start + block);
      let peak = 0;
      for (let j = start; j < end; j += 1) {
        peak = Math.max(peak, Math.abs(channelData[j]));
      }
      out[i] = peak;
    }
    return out;
  }

  function paintLegend(ctx, width, height, stats) {
    const pad = Math.max(8, width * 0.02);
    ctx.font = `${Math.max(10, Math.floor(height * 0.09))}px ui-sans-serif, system-ui, sans-serif`;
    ctx.textBaseline = "top";
    ctx.fillStyle = "rgba(243,239,230,0.55)";
    ctx.fillText("raw", pad, pad);
    ctx.fillStyle = "rgba(196, 92, 62, 0.85)";
    ctx.fillText("removed", pad + width * 0.12, pad);
    ctx.fillStyle = "#3dba8c";
    ctx.fillText("recorded", pad + width * 0.28, pad);

    if (!stats) return;
    ctx.fillStyle = "rgba(243,239,230,0.7)";
    ctx.textAlign = "right";
    const bits = [];
    if (stats.rmsIn != null) bits.push(`in ${db(stats.rmsIn)}`);
    if (stats.rmsOut != null) bits.push(`out ${db(stats.rmsOut)}`);
    if (stats.gain != null) bits.push(`×${Number(stats.gain).toFixed(1)}`);
    if (stats.gate != null && stats.gate < 0.99) bits.push("gate");
    if (stats.removed != null) bits.push(`Δ ${db(stats.removed)}`);
    ctx.fillText(bits.join("  ·  "), width - pad, pad);
    ctx.textAlign = "left";
  }

  function db(linear) {
    if (!linear || linear <= 0.00001) return "-∞ dB";
    return `${(20 * Math.log10(linear)).toFixed(0)} dB`;
  }

  global.AudioMixer = {
    PRESETS,
    defaults,
    loadSettings,
    saveSettings,
    applyPreset,
    createLiveSession,
    processBuffer,
    bufferToWavBlob,
    readLevel,
    createSignalPlane,
    peakEnvelope,
  };
})(window);
