import os
from pathlib import Path

MODEL_NAMES = (
    "PP-DocLayout-S",
    "PP-OCRv6_medium_det",
    "PP-OCRv6_medium_rec",
    "PP-OCRv6_small_rec",
    "PP-FormulaNet_plus-M",
    "PP-LCNet_x1_0_doc_ori",
)
MODEL_FILES = ("inference.json", "inference.pdiparams", "inference.yml")
ENGINE = {"run_mode": "paddle", "device_type": "cpu", "cpu_threads": 1, "enable_new_ir": False}
SOURCE_IMAGE = Path("/opt/shuxueshuo/internal/source-images/tj-2026-hexi-yimo-25/source-page-01.png")


def validate_cache(root=None):
    root = Path(root) if root is not None else Path.home() / ".paddlex/official_models"
    missing = [str(root / name / filename) for name in MODEL_NAMES for filename in MODEL_FILES
               if not (root / name / filename).is_file() or (root / name / filename).stat().st_size == 0]
    if missing:
        raise RuntimeError("Incomplete OCR model cache: " + ", ".join(missing))
    for name in MODEL_NAMES:
        print(name, "OK", root / name)


def main(image=SOURCE_IMAGE):
    os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "bos")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    from paddleocr import PaddleOCR
    from paddlex import create_model

    image = Path(image)
    if not image.is_file():
        raise FileNotFoundError(image)

    print("1/5 layout PP-DocLayout-S")
    layout = create_model(model_name="PP-DocLayout-S", engine="paddle_static", engine_config=ENGINE)
    list(layout.predict(str(image), batch_size=1, layout_nms=True))
    print("layout OK")

    print("2/5 text OCR PP-OCRv6_medium_det/rec")
    ocr = PaddleOCR(
        text_detection_model_name="PP-OCRv6_medium_det",
        text_recognition_model_name="PP-OCRv6_medium_rec",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=False,
    )
    list(ocr.predict(str(image)))
    print("text OCR OK")

    print("3/5 formula PP-FormulaNet_plus-M")
    formula = create_model(model_name="PP-FormulaNet_plus-M", engine="paddle_static", engine_config=ENGINE)
    list(formula.predict(str(image)))
    print("formula OK")

    print("4/5 orientation PP-LCNet_x1_0_doc_ori")
    orientation = create_model(model_name="PP-LCNet_x1_0_doc_ori", engine="paddle_static", engine_config=ENGINE)
    list(orientation.predict(str(image)))
    print("orientation OK")

    print("5/5 search heads PP-OCRv6_small_rec")
    heads = create_model(model_name="PP-OCRv6_small_rec", engine="paddle_static", engine_config=ENGINE)
    list(heads.predict(str(image)))
    print("search heads OK")

    validate_cache()
    print("PREHEAT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
