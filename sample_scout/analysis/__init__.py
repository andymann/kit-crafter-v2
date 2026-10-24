"""Audio analysis: mirrors the original ``sample_scout_tools`` crate.

Two tiers, matching the original's architecture (confirmed by the
literal strings ``"[ONNX] Tempo model unavailable — Tier 2 analysis
disabled"`` etc. found in the binary, and by the dedicated
``waveform::onnx_worker_loop`` worker that runs separately from the
fast synchronous scan path):

* **Tier 1** (``autocorrelation``, ``pitch``) runs synchronously while
  scanning and needs no ML model: onset-autocorrelation tempo detection
  (``bpm_acf``) and pYIN pitch detection (``pitch_note`` / ``pitch_freq``
  / ``pitch_cents`` / ``pitch_confidence``).
* **Tier 2** (``key_cnn``, ``tempo_cnn``) runs in a background worker
  using the two bundled ONNX models for higher-accuracy BPM
  (``bpm_beatthis``) and musical key (``key_cnn`` / ``key_cnn_numerical``).

Column priority, as recovered verbatim from the UPDATE statements in the
binary::

    bpm         = COALESCE(bpm_tag, bpm_filename, bpm_beatthis, bpm_acf)
    key_name    = COALESCE(key_tag, key_cnn)
    key_numerical = COALESCE(<key_tag's camelot code>, key_cnn_numerical)
"""
