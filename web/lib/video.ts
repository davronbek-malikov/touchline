/** Pull evenly spaced still frames from a video file in the browser, as JPEG blobs.
 *  The models read images, not video, so a clip is sent as a handful of frames. */
export async function extractFrames(file: File, count = 6, maxEdge = 1280):
  Promise<{ blob: Blob; at: number }[]> {
  const url = URL.createObjectURL(file);
  const video = document.createElement("video");
  video.muted = true;
  video.preload = "auto";
  video.src = url;
  try {
    await new Promise<void>((resolve, reject) => {
      video.onloadedmetadata = () => resolve();
      video.onerror = () => reject(new Error("This browser can't open that video format. Try MP4 or WebM."));
    });
    const duration = video.duration;
    if (!Number.isFinite(duration) || duration <= 0) throw new Error("That video has no readable length.");
    const scale = Math.min(1, maxEdge / Math.max(video.videoWidth, video.videoHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    const ctx = canvas.getContext("2d")!;
    const frames: { blob: Blob; at: number }[] = [];
    for (let i = 0; i < count; i++) {
      const at = (duration * (i + 0.5)) / count;
      await new Promise<void>((resolve) => { video.onseeked = () => resolve(); video.currentTime = at; });
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/jpeg", 0.82));
      if (blob) frames.push({ blob, at });
    }
    return frames;
  } finally {
    URL.revokeObjectURL(url);
  }
}

export function clock(seconds: number): string {
  const s = Math.round(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
