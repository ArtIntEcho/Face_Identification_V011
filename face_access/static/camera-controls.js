const cameraVideo = document.querySelector("#camera");
const serverCameraImage = document.querySelector("#server-camera");
const cameraStartButton = document.querySelector("#camera-start");
const cameraStopButton = document.querySelector("#camera-stop");
const cameraPlaceholder = document.querySelector("#camera-placeholder");
const cameraState = document.querySelector("#face-state");
const authenticationMessage = document.querySelector("#auth-message");
window.faceCameraMode = "browser";
let serverCameraActive = false;

const nativeGetUserMedia = navigator.mediaDevices?.getUserMedia?.bind(navigator.mediaDevices);
const cameraUnavailableMessage = window.isSecureContext
  ? "浏览器未提供摄像头接口。请检查摄像头设备和浏览器权限。"
  : "当前页面不是安全连接。请使用 HTTPS，或通过 SSH 端口转发后使用 localhost 访问。";

async function requestCamera(constraints) {
  if (!nativeGetUserMedia) throw new Error(cameraUnavailableMessage);
  return nativeGetUserMedia(constraints);
}

window.enrollmentGetUserMedia = requestCamera;
window.faceCameraIsActive = () => (
  window.faceCameraMode === "server" ? serverCameraActive : Boolean(cameraVideo.srcObject)
);

if (nativeGetUserMedia) {
  navigator.mediaDevices.getUserMedia = async (constraints) => {
    const stream = await requestCamera(constraints);
    cameraStartButton.hidden = true;
    cameraStopButton.hidden = false;
    setTimeout(() => document.dispatchEvent(new CustomEvent("face-camera-started")), 0);
    return stream;
  };
} else {
  cameraStartButton.addEventListener("click", (event) => {
    if (window.faceCameraMode === "server") return;
    event.preventDefault();
    event.stopImmediatePropagation();
    cameraState.textContent = "摄像头不可用";
    authenticationMessage.textContent = cameraUnavailableMessage;
  }, { capture: true });
}

cameraStartButton.addEventListener("click", (event) => {
  if (window.faceCameraMode !== "server") return;
  event.preventDefault();
  event.stopImmediatePropagation();
  serverCameraImage.src = `/api/camera/stream?t=${Date.now()}`;
  serverCameraImage.hidden = false;
  cameraVideo.hidden = true;
  cameraPlaceholder.classList.add("hidden");
  cameraStartButton.hidden = true;
  cameraStopButton.hidden = false;
  serverCameraActive = true;
  document.dispatchEvent(new CustomEvent("face-camera-started"));
}, { capture: true });

cameraStopButton.addEventListener("click", () => {
  if (window.faceCameraMode === "server") {
    serverCameraImage.removeAttribute("src");
    serverCameraImage.hidden = true;
    cameraVideo.hidden = false;
    serverCameraActive = false;
  }
  const stream = cameraVideo.srcObject;
  if (stream instanceof MediaStream) {
    stream.getTracks().forEach((track) => track.stop());
  }
  cameraVideo.srcObject = null;
  cameraPlaceholder.classList.remove("hidden");
  cameraState.textContent = "摄像头已关闭";
  authenticationMessage.textContent = "摄像头已关闭，视频轨道已释放。";
  cameraStopButton.hidden = true;
  cameraStartButton.hidden = false;
  document.dispatchEvent(new CustomEvent("face-camera-stopped"));
});

fetch("/api/camera/status")
  .then((response) => response.json())
  .then((status) => {
    window.faceCameraMode = status.mode || "browser";
    document.dispatchEvent(new CustomEvent("face-camera-mode", { detail: status }));
    if (status.mode === "server" && !status.available && status.error) {
      authenticationMessage.textContent = status.error;
    }
  })
  .catch(() => {
    window.faceCameraMode = "browser";
  });