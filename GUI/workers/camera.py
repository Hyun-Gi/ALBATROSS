"""Camera live-capture worker (QThread) — local webcam or RTSP (IP camera) -> emits QImage.

- source is an int  -> local webcam (Windows: CAP_DSHOW)
- source is a str   -> RTSP/HTTP stream (FFMPEG, low-latency options + buffered-frame drop)

The module imports fine even without opencv installed; run() reports it and exits.
Never hardcode credentials (passwords, etc.) in this file — build the URL in config and pass it in.
"""
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

try:
    import cv2
    HAS_CV2 = True
except Exception:
    HAS_CV2 = False

# RTSP low-latency options (Hikvision and other IP cameras). Same as the ProdTracker monitor code.
_RTSP_LOWLATENCY = (
    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay"
    "|probesize;32|analyzeduration;0|max_delay;0|reorder_queue_size;0"
)


class CameraWorker(QThread):
    frame = pyqtSignal(QImage)      # new frame (RGB QImage)
    failed = pyqtSignal(str)        # open/read failure

    def __init__(self, source=0, fps=25, size=(960, 540)):
        super().__init__()
        self.source = source                              # int (webcam) or str (RTSP URL)
        self._delay = max(1, int(1000 / max(1, fps)))     # ms/frame
        self.size = size                                  # resize target (None = original)
        self._running = True

    def stop(self):
        self._running = False
        self.wait(2000)             # wait for the capture loop to exit and release

    def _open(self):
        if isinstance(self.source, str):                  # RTSP/HTTP IP camera
            import os
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = _RTSP_LOWLATENCY
            cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
        else:                                             # local webcam
            cap = cv2.VideoCapture(int(self.source), cv2.CAP_DSHOW)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        return cap

    def _src_label(self):
        """Source label for logging — masks the password portion of RTSP URLs."""
        if isinstance(self.source, str):
            tail = self.source.split("@", 1)[-1]
            return "rtsp://…@" + tail
        return f"webcam index {self.source}"

    def run(self):
        if not HAS_CV2:
            self.failed.emit("opencv not installed — pip install opencv-python")
            return
        cap = self._open()
        if not cap or not cap.isOpened():
            self.failed.emit(f"Cannot open camera: {self._src_label()} (in use by another app / check address and permissions)")
            return
        is_stream = isinstance(self.source, str)
        try:
            while self._running:
                if is_stream:
                    for _ in range(2):          # drop buffered frames to keep latency low
                        if not cap.grab():
                            break
                    ok, frame = cap.retrieve()
                else:
                    ok, frame = cap.read()
                if not ok or frame is None:
                    self.failed.emit("Failed to read a frame.")
                    break
                if self.size:
                    frame = cv2.resize(frame, self.size)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb.shape
                # .copy() — the numpy buffer is overwritten next loop, so let QImage own a copy
                img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
                self.frame.emit(img)
                self.msleep(self._delay)
        finally:
            cap.release()
