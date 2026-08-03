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
const captureCanvas = document.createElement("canvas");
let authenticationGeneration = 0;

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
  if (payload.status === "waiting_for_face") return payload.message || "请将一张人脸置于画面中央";
  if (payload.status === "waiting_for_blink") return "请保持正对摄像头并自然眨眼";
  if (payload.status === "waiting_for_turn") {
    return payload.required_turn === "left" ? "请向画面右侧转头" : "请向画面左侧转头";
  }
  if (payload.status === "accepted") {
    return `认证通过：${payload.person_name}，操作等级 ${payload.operation_level}`;
  }
  const failures = {
    challenge_timeout: "认证超时，请立即重试",
    blink_timeout: "未识别到眨眼，请立即重试",
    turn_timeout: "未识别到指定方向转头，请立即重试",
    passive_liveness_failed: "被动活体检测未通过",
    face_not_recognized: "未在授权人员库中找到匹配人员",
  };
  return `认证拒绝：${failures[payload.failure_reason] || payload.failure_reason || "未知原因"}`;
}

function renderAuthenticationState(payload) {
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
  } else if (payload.status === "waiting_for_turn") {
    const turnRightOnScreen = payload.required_turn === "left";
    authStep.textContent = "第 2 步 / 2";
    authInstruction.textContent = turnRightOnScreen ? "请向画面右侧转头 →" : "← 请向画面左侧转头";
    authDetail.textContent = "预览为镜像画面，请跟随箭头缓慢转动约 20°";
    faceState.textContent = "等待转头";
  } else if (payload.status === "accepted") {
    authStep.textContent = "认证完成";
    authInstruction.textContent = `认证通过 · ${payload.person_name}`;
    authDetail.textContent = `操作等级 ${payload.operation_level}`;
    faceState.textContent = "认证通过";
  } else if (payload.status === "rejected") {
    authStep.textContent = "认证未通过";
    authInstruction.textContent = explainResult(payload).replace("认证拒绝：", "");
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
});