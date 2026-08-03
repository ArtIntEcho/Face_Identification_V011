const cameraVideo = document.querySelector("#camera");
const cameraStartButton = document.querySelector("#camera-start");
const cameraStopButton = document.querySelector("#camera-stop");
const cameraPlaceholder = document.querySelector("#camera-placeholder");
const cameraState = document.querySelector("#face-state");
const authenticationMessage = document.querySelector("#auth-message");

const getUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
window.enrollmentGetUserMedia = getUserMedia;
navigator.mediaDevices.getUserMedia = async (constraints) => {
  const stream = await getUserMedia(constraints);
  cameraStartButton.hidden = true;
  cameraStopButton.hidden = false;
  setTimeout(() => document.dispatchEvent(new CustomEvent("face-camera-started")), 0);
  return stream;
};

cameraStopButton.addEventListener("click", () => {
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