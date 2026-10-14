const authVideo = document.querySelector("#camera");
const authMessage = document.querySelector("#auth-message");
const faceState = document.querySelector("#face-state");
const timer = document.querySelector("#timer");
const authOverlay = document.querySelector("#auth-overlay");
const authStep = document.querySelector("#auth-step");
const authInstruction = document.querySelector("#auth-instruction");
const authDetail = document.querySelector("#auth-detail");
const authCountdown = document.querySelector("#auth-countdown");
const authProgressBar = document.querySelector("#auth-progress-bar");
const authRetry = document.querySelector("#auth-retry");
const detectionOverlay = document.querySelector("#detection-overlay");
const detectionOverlayToggle = document.querySelector("#detection-overlay-toggle");
const captureCanvas = document.createElement("canvas");
let authenticationGeneration = 0;
let latestAuthenticationPayload = null;

function renderFaceDetection(detection) {
  const context = detectionOverlay.getContext("2d");
  const displayWidth = detectionOverlay.clientWidth;
  const displayHeight = detectionOverlay.clientHeight;
  detectionOverlay.width = displayWidth;
  detectionOverlay.height = displayHeight;
  context.clearRect(0, 0, displayWidth, displayHeight);
  if (!detectionOverlayToggle.checked || !detection || !captureCanvas.width) return;
  const scale = Math.max(displayWidth / captureCanvas.width, displayHeight / captureCanvas.height);
  const offsetX = (displayWidth - captureCanvas.width * scale) / 2;
  const offsetY = (displayHeight - captureCanvas.height * scale) / 2;
  const width = detection.width * scale;
  const height = detection.height * scale;
  const x = displayWidth - offsetX - detection.x * scale - width;
  const y = offsetY + detection.y * scale;
  const label = `${window.t("人脸")} ${(detection.confidence * 100).toFixed(1)}%`;
  context.strokeStyle = "#e2ff70";
  context.lineWidth = 2;
  context.strokeRect(x, y, width, height);
  context.font = "600 13px Aptos, sans-serif";
  const labelWidth = context.measureText(label).width + 12;
  context.fillStyle = "rgba(17, 23, 19, .88)";
  context.fillRect(x, Math.max(0, y - 25), labelWidth, 25);
  context.fillStyle = "#e2ff70";
  context.fillText(label, x + 6, Math.max(17, y - 7));
}

function captureFrame() {
  if (!authVideo.videoWidth || !authVideo.videoHeight) return Promise.resolve(null);
  const width = Math.min(authVideo.videoWidth, 960);
  const height = Math.round(authVideo.videoHeight * width / authVideo.videoWidth);
  captureCanvas.width = width;
  captureCanvas.height = height;
  captureCanvas.getContext("2d").drawImage(authVideo, 0, 0, width, height);
  return new Promise((resolve) => captureCanvas.toBlob(resolve, "image/jpeg", 0.88));
}

function explainResult(payload) {
  if (payload.status === "waiting_for_face") return window.t(payload.message || "请将一张人脸置于画面中央");
  if (payload.status === "waiting_for_blink") return window.t("请保持正对摄像头并自然眨眼");
  if (["waiting_for_action", "waiting_for_turn"].includes(payload.status)) {
    return window.t(`action_${payload.required_action || payload.required_turn}`);
  }
  if (payload.status === "accepted") {
    return `${window.t("认证通过")}：${payload.person_name}，${window.t("操作等级")} ${payload.operation_level}`;
  }
  const failures = {
    challenge_timeout: "认证超时，请立即重试",
    blink_timeout: "未识别到眨眼，请立即重试",
    turn_timeout: "未识别到指定方向转头，请立即重试",
    action_timeout: "未识别到指定头部动作，请立即重试",
    passive_liveness_failed: "被动活体检测未通过",
    face_not_recognized: "未在授权人员库中找到匹配人员",
  };
  const reason = failures[payload.failure_reason] || payload.failure_reason || "未知原因";
  return `${window.t("认证拒绝")}：${window.t(reason)}`;
}

function renderAuthenticationState(payload) {
  latestAuthenticationPayload = payload;
  renderFaceDetection(payload.face_detection);
  const timeout = payload.timeout_seconds || 15;
  const remaining = payload.remaining_seconds ?? timeout;
  const progress = Math.max(0, Math.min(100, remaining / timeout * 100));
  authOverlay.hidden = false;
  authOverlay.dataset.status = payload.status;
  authCountdown.textContent = `${remaining.toFixed(1)}s`;
  authProgressBar.style.width = `${progress}%`;
  timer.textContent = `${remaining.toFixed(1)}s`;
  if (payload.status === "waiting_for_face") {
    authStep.textContent = "准备认证";
    authInstruction.textContent = payload.message || "请将人脸置于画面中央";
    authDetail.textContent = "请确保画面中只有一人";
    faceState.textContent = "等待单张人脸";
  } else if (payload.status === "waiting_for_blink") {
    authStep.textContent = "第 1 步 / 2";
    authInstruction.textContent = "请自然眨眼一次";
    authDetail.textContent = "保持正对摄像头，闭眼后重新睁开";
    faceState.textContent = "等待眨眼";
  } else if (["waiting_for_action", "waiting_for_turn"].includes(payload.status)) {
    const action = payload.required_action || payload.required_turn;
    authStep.textContent = "第 2 步 / 2";
    authInstruction.textContent = window.t(`action_${action}`);
    authDetail.textContent = ["left", "right"].includes(action)
      ? window.t("预览为镜像画面，请跟随箭头缓慢转动约 20°")
      : window.t("保持面部居中，轻微抬起或收起下巴");
    faceState.textContent = window.t("等待头部动作");
  } else if (payload.status === "accepted") {
    authStep.textContent = "认证完成";
    authInstruction.textContent = `${window.t("认证通过")} · ${payload.person_name}`;
    authDetail.textContent = `${window.t("操作等级")} ${payload.operation_level}`;
    faceState.textContent = "认证通过";
  } else if (payload.status === "rejected") {
    authStep.textContent = "认证未通过";
    authInstruction.textContent = explainResult(payload).replace(`${window.t("认证拒绝")}：`, "");
    authDetail.textContent = "调整位置后可直接重试，无需关闭摄像头";
    faceState.textContent = "认证拒绝";
  }
}

async function runAuthentication(generation) {
  try {
    const startResponse = await fetch("/api/authentication/challenges", { method: "POST" });
    const challenge = await startResponse.json();
    if (!startResponse.ok) throw new Error(challenge.detail || "无法创建认证挑战");
    while (generation === authenticationGeneration && authVideo.srcObject) {
      const blob = await captureFrame();
      if (!blob) {
        await new Promise((resolve) => setTimeout(resolve, 100));
        continue;
      }
      const body = new FormData();
      body.append("frame", blob, "camera.jpg");
      const response = await fetch(`/api/authentication/challenges/${challenge.challenge_id}/frames`, {
        method: "POST",
        body,
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "认证帧处理失败");
      renderAuthenticationState(payload);
      authMessage.textContent = explainResult(payload);
      if (["accepted", "rejected"].includes(payload.status)) {
        authRetry.hidden = payload.status === "accepted";
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 350));
    }
  } catch (error) {
    if (generation === authenticationGeneration) {
      faceState.textContent = "认证不可用";
      authMessage.textContent = error.message;
    }
  }
}

document.addEventListener("face-camera-started", () => {
  authenticationGeneration += 1;
  timer.textContent = "15.0s";
  authRetry.hidden = true;
  runAuthentication(authenticationGeneration);
});

authRetry.addEventListener("click", () => {
  authenticationGeneration += 1;
  authRetry.hidden = true;
  authMessage.textContent = "正在开始新的认证挑战...";
  runAuthentication(authenticationGeneration);
});

document.addEventListener("face-camera-stopped", () => {
  authenticationGeneration += 1;
  timer.textContent = "00.0s";
  authOverlay.hidden = true;
  authRetry.hidden = true;
  renderFaceDetection(null);
});

detectionOverlayToggle.checked = localStorage.getItem("face-access-overlay") !== "hidden";
detectionOverlayToggle.addEventListener("change", () => {
  localStorage.setItem("face-access-overlay", detectionOverlayToggle.checked ? "visible" : "hidden");
  if (!detectionOverlayToggle.checked) renderFaceDetection(null);
});

document.addEventListener("face-language-changed", () => {
  if (latestAuthenticationPayload) renderAuthenticationState(latestAuthenticationPayload);
});