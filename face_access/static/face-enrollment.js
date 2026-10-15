async function uploadFacePhotos(personId, files) {
  if (!files.length) return null;
  const body = new FormData();
  [...files].forEach((file) => body.append("files", file));
  const response = await fetch(`/api/people/${encodeURIComponent(personId)}/faces`, {
    method: "POST",
    credentials: "same-origin",
    body,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || `注册失败 (${response.status})`);
  return payload;
}

const enrollmentDialog = document.querySelector("#enroll-dialog");
const enrollmentForm = document.querySelector("#enroll-form");
const enrollmentVideo = document.querySelector("#enroll-camera");
const enrollmentServerImage = document.querySelector("#enroll-server-camera");
const enrollmentSubmit = document.querySelector("#enroll-submit");
const captureButton = document.querySelector("#enroll-capture");
const enrollmentCaptureCanvas = document.createElement("canvas");
const capturePoses = [
  ["正面平视", "脸部居中，保持自然表情"],
  ["稍向左转", "缓慢向画面左侧转动约 20°"],
  ["稍向右转", "缓慢向画面右侧转动约 20°"],
  ["轻微抬头", "下巴稍微抬起，眼睛看向镜头"],
  ["轻微低头", "下巴稍微收起，眼睛看向镜头"],
];
let enrollmentMode = "camera";
let enrollmentStream = null;
let capturedPhotos = Array(capturePoses.length).fill(null);
let previewUrls = [];

function stopEnrollmentCamera() {
  if (typeof MediaStream !== "undefined" && enrollmentStream instanceof MediaStream) {
    enrollmentStream.getTracks().forEach((track) => track.stop());
  }
  enrollmentStream = null;
  enrollmentVideo.srcObject = null;
  enrollmentVideo.hidden = false;
  enrollmentServerImage.removeAttribute("src");
  enrollmentServerImage.hidden = true;
  document.querySelector("#enroll-camera-placeholder").hidden = false;
  document.querySelector("#enroll-camera-start").textContent = "启动摄像头";
  captureButton.disabled = true;
}

function updateCaptureView() {
  previewUrls.forEach((url) => URL.revokeObjectURL(url));
  previewUrls = [];
  const completedCount = capturedPhotos.filter(Boolean).length;
  const poseIndex = capturedPhotos.findIndex((photo) => !photo);
  document.querySelector("#capture-pose").textContent = poseIndex === -1 ? "采集完成" : capturePoses[poseIndex][0];
  document.querySelector("#capture-hint").textContent = poseIndex === -1
    ? "可选择任意照片重拍，或直接生成模板"
    : capturePoses[poseIndex][1];
  const items = capturePoses.map(([pose], index) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = `capture-item${capturedPhotos[index] ? " complete" : ""}`;
    item.dataset.captureIndex = String(index);
    if (capturedPhotos[index]) {
      const image = document.createElement("img");
      const previewUrl = URL.createObjectURL(capturedPhotos[index]);
      previewUrls.push(previewUrl);
      image.src = previewUrl;
      image.alt = pose;
      item.append(image);
    } else {
      const number = document.createElement("span");
      number.textContent = String(index + 1);
      item.append(number);
    }
    const label = document.createElement("small");
    label.textContent = capturedPhotos[index] ? `${pose} · 重拍` : pose;
    item.append(label);
    return item;
  });
  document.querySelector("#capture-list").replaceChildren(...items);
  captureButton.disabled = !enrollmentStream || completedCount === capturePoses.length;
  enrollmentSubmit.disabled = enrollmentMode === "camera"
    ? completedCount < capturePoses.length
    : !enrollmentForm.face_photos.files.length;
}

function setEnrollmentMode(mode) {
  enrollmentMode = mode;
  const cameraMode = mode === "camera";
  document.querySelector("#enroll-camera-panel").hidden = !cameraMode;
  document.querySelector("#enroll-upload-panel").hidden = cameraMode;
  document.querySelector("#enroll-mode-camera").classList.toggle("active", cameraMode);
  document.querySelector("#enroll-mode-upload").classList.toggle("active", !cameraMode);
  document.querySelector("#enroll-mode-camera").setAttribute("aria-selected", String(cameraMode));
  document.querySelector("#enroll-mode-upload").setAttribute("aria-selected", String(!cameraMode));
  if (!cameraMode) stopEnrollmentCamera();
  updateCaptureView();
}

document.querySelector("#enroll-camera-start").addEventListener("click", async () => {
  if (enrollmentStream) {
    stopEnrollmentCamera();
    return;
  }
  const result = document.querySelector("#enroll-result");
  try {
    if (window.faceCameraMode === "server") {
      enrollmentStream = { server: true };
      enrollmentVideo.hidden = true;
      enrollmentServerImage.src = `/api/camera/stream?t=${Date.now()}`;
      enrollmentServerImage.hidden = false;
    } else {
      enrollmentStream = await window.enrollmentGetUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      enrollmentVideo.srcObject = enrollmentStream;
      await enrollmentVideo.play();
    }
    document.querySelector("#enroll-camera-placeholder").hidden = true;
    document.querySelector("#enroll-camera-start").textContent = "关闭摄像头";
    result.textContent = "";
    updateCaptureView();
  } catch (error) {
    result.textContent = `无法访问摄像头：${error.message}`;
    stopEnrollmentCamera();
  }
});

captureButton.addEventListener("click", async () => {
  const poseIndex = capturedPhotos.findIndex((photo) => !photo);
  if (poseIndex === -1) return;
  const result = document.querySelector("#enroll-result");
  try {
    let blob;
    if (window.faceCameraMode === "server") {
      const response = await fetch(`/api/camera/frame?t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`无法获取摄像头画面 (${response.status})`);
      blob = await response.blob();
    } else {
      if (!enrollmentVideo.videoWidth) return;
      enrollmentCaptureCanvas.width = enrollmentVideo.videoWidth;
      enrollmentCaptureCanvas.height = enrollmentVideo.videoHeight;
      enrollmentCaptureCanvas.getContext("2d").drawImage(enrollmentVideo, 0, 0);
      blob = await new Promise((resolve) => enrollmentCaptureCanvas.toBlob(resolve, "image/jpeg", 0.92));
    }
    if (!blob) return;
    capturedPhotos[poseIndex] = new File([blob], `camera-${poseIndex + 1}.jpg`, { type: "image/jpeg" });
    result.textContent = "";
    updateCaptureView();
  } catch (error) {
    result.textContent = error.message;
  }
});

document.querySelector("#capture-list").addEventListener("click", (event) => {
  const item = event.target.closest("[data-capture-index]");
  const index = Number(item?.dataset.captureIndex);
  if (!Number.isInteger(index) || !capturedPhotos[index]) return;
  capturedPhotos[index] = null;
  updateCaptureView();
});

document.querySelector("#enroll-mode-camera").addEventListener("click", () => setEnrollmentMode("camera"));
document.querySelector("#enroll-mode-upload").addEventListener("click", () => setEnrollmentMode("upload"));
enrollmentForm.face_photos.addEventListener("change", updateCaptureView);

enrollmentForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const result = document.querySelector("#enroll-result");
  result.textContent = "正在检测并生成模板...";
  try {
    const files = enrollmentMode === "camera" ? capturedPhotos.filter(Boolean) : form.face_photos.files;
    if (!files.length) throw new Error("请先采集或选择人脸照片");
    enrollmentSubmit.disabled = true;
    const payload = await uploadFacePhotos(form.person_id.value, files);
    const failures = payload.failures.map((item) => `${item.filename}: ${item.reason}`).join("；");
    result.textContent = `成功 ${payload.success_count} 张，失败 ${payload.failure_count} 张${failures ? `。${failures}` : ""}`;
    if (!payload.failure_count) {
      form.face_photos.value = "";
      capturedPhotos = Array(capturePoses.length).fill(null);
      stopEnrollmentCamera();
      updateCaptureView();
    } else {
      enrollmentSubmit.disabled = false;
    }
  } catch (error) {
    result.textContent = error.message;
    updateCaptureView();
  }
});

document.querySelector("#enroll-open").addEventListener("click", async () => {
  const form = document.querySelector("#enroll-form");
  document.querySelector("#enroll-result").textContent = "";
  try {
    if (window.faceCameraIsActive()) document.querySelector("#camera-stop").click();
    const response = await fetch("/api/people", { credentials: "same-origin" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "无法读取授权人员");
    const activePeople = payload.filter((person) => person.status === "active");
    form.person_id.replaceChildren(...activePeople.map((person) => {
      const option = document.createElement("option");
      option.value = person.person_id;
      option.textContent = `${person.name} (${person.person_id})`;
      return option;
    }));
    if (!activePeople.length) throw new Error("请先新增一名启用的授权人员");
    capturedPhotos = Array(capturePoses.length).fill(null);
    form.face_photos.value = "";
    setEnrollmentMode("camera");
    enrollmentDialog.showModal();
  } catch (error) {
    document.querySelector("#people-empty").textContent = error.message;
  }
});

enrollmentDialog.addEventListener("close", stopEnrollmentCamera);

window.uploadFacePhotos = uploadFacePhotos;