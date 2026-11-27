/** Friendly, actionable messages for backend and camera error codes. */

export interface FriendlyMessage {
  title: string;
  hint: string;
}

export const SELFIE_MESSAGES: Record<string, FriendlyMessage> = {
  NO_FACE: {
    title: "We couldn't see a face",
    hint: "Look straight at the camera in good light, with your whole face inside the circle.",
  },
  MULTIPLE_FACES: {
    title: "More than one face found",
    hint: "Make sure only you are in the selfie — step away from friends for a moment.",
  },
  FACE_TOO_SMALL: {
    title: "Your face is too small",
    hint: "Move a little closer so your face fills the circle.",
  },
  TOO_BLURRY: {
    title: "That one came out blurry",
    hint: "Hold your phone steady and try again.",
  },
  TOO_DARK: {
    title: "It's a bit too dark",
    hint: "Turn towards a window or a light and try again.",
  },
  TOO_BRIGHT: {
    title: "Too much light",
    hint: "Avoid strong light shining directly on you or right behind you.",
  },
  INVALID_IMAGE: {
    title: "That file isn't a photo we can read",
    hint: "Please use a JPEG, PNG, WebP or HEIC image.",
  },
  FILE_TOO_LARGE: {
    title: "That photo is too large",
    hint: "Please choose a photo under 8 MB.",
  },
};

export const CAMERA_MESSAGES: Record<"denied" | "unavailable" | "error", FriendlyMessage> = {
  denied: {
    title: "Camera access is blocked",
    hint: "Allow camera access in your browser settings and reload, or upload a selfie instead.",
  },
  unavailable: {
    title: "No camera available",
    hint: "We couldn't find a camera on this device. You can upload a selfie instead.",
  },
  error: {
    title: "The camera couldn't start",
    hint: "Close other apps that may be using the camera, or upload a selfie instead.",
  },
};

export function selfieMessage(code: string): FriendlyMessage {
  return SELFIE_MESSAGES[code] ?? { title: "We couldn't use that selfie", hint: "Please try another photo." };
}

export const TIPS = [
  "Find good, even light — face a window if you can",
  "Look straight at the camera with your face inside the circle",
  "Remove sunglasses, masks or hats that hide your face",
  "Try adding a second selfie from a slightly different angle",
];
