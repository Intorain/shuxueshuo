"""Page orientation protocol shared by OCR and full-resolution image storage.

The public rotation is clockwise. Paddle's classifier label is the angle used
by its document preprocessor for a counterclockwise correction.
"""

import math

from PIL import Image

MIN_CONFIDENCE = 0.90
ANGLES = (0, 90, 180, 270)


def rotate_clockwise(image: Image.Image, degrees: int) -> Image.Image:
    """Apply an exact quarter turn, preserving all pixels and swapping dimensions."""
    if type(degrees) is not int or degrees not in ANGLES:
        raise ValueError("orientation.invalid_rotation")
    operations = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180,
                  270: Image.Transpose.ROTATE_90}
    return image.transpose(operations[degrees]) if degrees else image.copy()


def uncertain_orientation(reason: str) -> dict:
    return {"status": "uncertain", "rotation_degrees": 0,
            "predicted_degrees": None, "confidence": None, "reason": reason}


def orientation_from_prediction(prediction: dict) -> dict:
    """Trust only a supported class with a finite, sufficiently confident score."""
    try:
        label, score = prediction["label_names"][0], prediction["scores"][0]
        if label not in ("0", "90", "180", "270") or isinstance(score, bool):
            return uncertain_orientation("invalid_prediction")
        confidence = float(score)
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            return uncertain_orientation("invalid_prediction")
    except (KeyError, IndexError, TypeError, ValueError):
        return uncertain_orientation("invalid_prediction")
    correction = (-int(label)) % 360
    if confidence < MIN_CONFIDENCE:
        return {"status": "uncertain", "rotation_degrees": 0,
                "predicted_degrees": correction, "confidence": confidence, "reason": "low_confidence"}
    return {"status": "corrected" if correction else "upright", "rotation_degrees": correction,
            "predicted_degrees": correction, "confidence": confidence}
