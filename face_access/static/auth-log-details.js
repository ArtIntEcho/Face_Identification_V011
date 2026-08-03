const authenticationFailureLabels = {
  blink_timeout: "眨眼超时",
  turn_timeout: "转头超时",
  challenge_timeout: "活体超时（旧记录）",
  passive_liveness_failed: "被动活体未通过",
  face_not_recognized: "未识别到授权人员",
};

const authenticationLogsBody = document.querySelector("#logs-body");
let enhancingAuthenticationLogs = false;

function formatAuthenticationStage(log) {
  const label = log.failure_reason
    ? authenticationFailureLabels[log.failure_reason] || log.failure_reason
    : "通过";
  try {
    const timings = JSON.parse(log.stage_timings_json || "{}");
    const stages = [];
    if (Number.isFinite(timings.blink_ms)) stages.push(`眨眼 ${(timings.blink_ms / 1000).toFixed(1)}s`);
    if (Number.isFinite(timings.turn_ms)) stages.push(`转头 ${(timings.turn_ms / 1000).toFixed(1)}s`);
    return stages.length ? `${label} · ${stages.join(" / ")}` : label;
  } catch {
    return label;
  }
}

async function enhanceAuthenticationLogs() {
  const rows = [...authenticationLogsBody.rows];
  if (enhancingAuthenticationLogs || !rows.some((row) => row.cells.length === 7)) return;
  enhancingAuthenticationLogs = true;
  try {
    const params = new URLSearchParams();
    new FormData(document.querySelector("#log-filter")).forEach((value, key) => {
      if (value) params.set(key, String(value));
    });
    const response = await fetch(`/api/logs${params.size ? `?${params}` : ""}`, {
      credentials: "same-origin",
    });
    if (!response.ok) return;
    const logs = await response.json();
    rows.forEach((row, index) => {
      if (row.cells.length !== 7 || !logs[index]) return;
      const cell = row.insertCell(2);
      cell.textContent = formatAuthenticationStage(logs[index]);
    });
  } finally {
    enhancingAuthenticationLogs = false;
  }
}

new MutationObserver(enhanceAuthenticationLogs).observe(authenticationLogsBody, {
  childList: true,
  subtree: true,
});