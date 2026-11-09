"""
scanner_core.py - phiên bản KHÔNG dùng OpenCV (chỉ numpy + Pillow) để build được cho iOS/Android.

Quy ước: ảnh dạng numpy uint8 (H, W, 3) theo thứ tự RGB.
Các hàm public giữ nguyên tên và chữ ký như bản OpenCV cũ.
"""
import numpy as np
from PIL import Image, ImageFilter, ImageOps


class DocumentScanner:
    # Cạnh dài tối đa sau khi xử lý (~A4 @ 300 DPI). PDF cuối cùng chỉ cần 1754px nên dư dùng,
    # đồng thời tránh tốn RAM trên điện thoại.
    MAX_LONG_SIDE = 2480

    # ------------------------------------------------------------------ hình học
    @staticmethod
    def order_points(pts):
        """Sắp xếp 4 góc: trên-trái, trên-phải, dưới-phải, dưới-trái."""
        pts = np.asarray(pts, dtype="float32")
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        return rect

    @staticmethod
    def _perspective_coeffs(dst_pts, src_pts):
        """Hệ số 8 tham số cho Image.transform(PERSPECTIVE): ánh xạ điểm đích -> điểm nguồn."""
        A = []
        B = []
        for (x, y), (X, Y) in zip(dst_pts, src_pts):
            A.append([x, y, 1, 0, 0, 0, -x * X, -y * X])
            B.append(X)
            A.append([0, 0, 0, x, y, 1, -x * Y, -y * Y])
            B.append(Y)
        return np.linalg.solve(np.array(A, dtype="float64"), np.array(B, dtype="float64"))

    @staticmethod
    def four_point_transform(image: np.ndarray, pts) -> np.ndarray:
        """Cắt theo khung giấy và nắn thẳng phối cảnh."""
        rect = DocumentScanner.order_points(pts)
        (tl, tr, br, bl) = rect

        widthA = np.hypot(br[0] - bl[0], br[1] - bl[1])
        widthB = np.hypot(tr[0] - tl[0], tr[1] - tl[1])
        max_w = max(int(widthA), int(widthB), 1)

        heightA = np.hypot(tr[0] - br[0], tr[1] - br[1])
        heightB = np.hypot(tl[0] - bl[0], tl[1] - bl[1])
        max_h = max(int(heightA), int(heightB), 1)

        dst = [(0, 0), (max_w - 1, 0), (max_w - 1, max_h - 1), (0, max_h - 1)]
        coeffs = DocumentScanner._perspective_coeffs(dst, rect.tolist())

        pil = Image.fromarray(image)
        warped = pil.transform(
            (max_w, max_h), Image.Transform.PERSPECTIVE, tuple(coeffs), resample=Image.Resampling.BICUBIC
        )
        return np.asarray(warped)

    # ------------------------------------------------------------------ nhận diện tờ giấy
    @staticmethod
    def _otsu_threshold(gray: np.ndarray) -> int:
        hist = np.bincount(gray.ravel(), minlength=256).astype("float64")
        total = gray.size
        sum_all = np.dot(np.arange(256), hist)
        w_b = 0.0
        sum_b = 0.0
        best_var, best_t = -1.0, 127
        for t in range(256):
            w_b += hist[t]
            if w_b == 0:
                continue
            w_f = total - w_b
            if w_f == 0:
                break
            sum_b += t * hist[t]
            m_b = sum_b / w_b
            m_f = (sum_all - sum_b) / w_f
            var = w_b * w_f * (m_b - m_f) ** 2
            if var > best_var:
                best_var, best_t = var, t
        return best_t

    @staticmethod
    def _polygon_area(p) -> float:
        x = p[:, 0]
        y = p[:, 1]
        return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))

    @staticmethod
    def auto_crop_document(image: np.ndarray) -> np.ndarray:
        """
        Tìm tờ giấy (vùng sáng lớn nhất so với nền) và nắn phẳng.
        Nếu không chắc chắn, trả về ảnh gốc để không cắt mất chữ.
        """
        h, w = image.shape[:2]
        scale = 500.0 / h
        small_w = max(1, int(w * scale))
        thumb = Image.fromarray(image).resize((small_w, 500), Image.Resampling.BILINEAR)
        gray_img = thumb.convert("L").filter(ImageFilter.GaussianBlur(3))
        gray = np.asarray(gray_img)

        t = DocumentScanner._otsu_threshold(gray)
        mask_img = Image.fromarray(((gray > t) * 255).astype("uint8"))
        # Median lọc nhiễu lẻ tẻ và lấp các lỗ nhỏ do chữ
        mask_img = mask_img.filter(ImageFilter.MedianFilter(9))
        mask = np.asarray(mask_img) > 127

        total = mask.size
        frac = mask.sum() / total
        # Tờ giấy phải chiếm 25%..97% khung hình; ngoài khoảng này coi như không tách được nền
        if frac < 0.25 or frac > 0.97:
            return image

        ys, xs = np.nonzero(mask)
        xs = xs.astype("float32")
        ys = ys.astype("float32")
        s = xs + ys
        d = xs - ys
        quad = np.array([
            [xs[np.argmin(s)], ys[np.argmin(s)]],  # trên-trái
            [xs[np.argmax(d)], ys[np.argmax(d)]],  # trên-phải
            [xs[np.argmax(s)], ys[np.argmax(s)]],  # dưới-phải
            [xs[np.argmin(d)], ys[np.argmin(d)]],  # dưới-trái
        ], dtype="float32")

        quad_area = DocumentScanner._polygon_area(quad)
        if quad_area < total * 0.25:
            return image
        # Vùng sáng phải lấp đầy tứ giác thì mới tin đó là tờ giấy hình chữ nhật
        fill = mask.sum() / max(quad_area, 1.0)
        if not (0.6 <= fill <= 1.15):
            return image

        return DocumentScanner.four_point_transform(image, quad / scale)

    # ------------------------------------------------------------------ làm rõ chữ
    @staticmethod
    def _blur_large(gray_img: Image.Image, radius: float) -> Image.Image:
        """Blur bán kính lớn nhanh: thu nhỏ -> blur -> phóng to."""
        w, h = gray_img.size
        f = 8
        small = gray_img.resize((max(1, w // f), max(1, h // f)), Image.Resampling.BILINEAR)
        small = small.filter(ImageFilter.GaussianBlur(max(1.0, radius / f)))
        return small.resize((w, h), Image.Resampling.BILINEAR)

    @staticmethod
    def enhance_document(image: np.ndarray, mode: str = "color", contrast: float = 1.25) -> np.ndarray:
        """
        mode = 'color': san phẳng ánh sáng nền, giữ màu (con dấu đỏ), tăng tương phản.
        mode = 'bw'   : đen trắng bằng ngưỡng thích nghi cục bộ.
        """
        pil = Image.fromarray(image)
        gray_img = pil.convert("L")
        short_side = min(pil.size)

        if mode == "bw":
            gray_img = gray_img.filter(ImageFilter.GaussianBlur(1))
            radius = max(7, short_side // 80)
            local_mean = np.asarray(DocumentScanner._blur_large(gray_img, radius * 2)).astype("int16")
            g = np.asarray(gray_img).astype("int16")
            bw = np.where(g > local_mean - 10, 255, 0).astype("uint8")
            return np.stack([bw, bw, bw], axis=-1)

        # Chế độ màu: chia cho độ sáng nền để xóa bóng / sáng không đều
        bg = np.asarray(DocumentScanner._blur_large(gray_img, max(20, short_side // 10))).astype("float32")
        gain = 255.0 / np.maximum(bg, 40.0)
        out = image.astype("float32") * gain[..., None]
        out = np.clip(out, 0, 255)
        # Tăng tương phản quanh mức xám giữa
        out = (out - 128.0) * contrast + 128.0 + 5.0
        return np.clip(out, 0, 255).astype("uint8")

    # ------------------------------------------------------------------ xoay
    @staticmethod
    def rotate_90(image: np.ndarray, clockwise: bool = True) -> np.ndarray:
        """Xoay ảnh 90 độ."""
        return np.ascontiguousarray(np.rot90(image, k=-1 if clockwise else 1))

    # ------------------------------------------------------------------ pipeline
    @staticmethod
    def process_file(input_path: str, output_path: str, auto_crop: bool = True,
                     mode: str = "color", rotate_steps: int = 0):
        """Đọc ảnh -> cắt mép -> xoay -> làm rõ chữ -> lưu JPEG chất lượng cao."""
        try:
            with Image.open(input_path) as im:
                im = ImageOps.exif_transpose(im)  # xoay theo EXIF của điện thoại
                img = np.asarray(im.convert("RGB"))
        except Exception as e:
            raise ValueError(f"Không thể đọc được file ảnh: {input_path} ({e})")

        if auto_crop:
            img = DocumentScanner.auto_crop_document(img)

        for _ in range(rotate_steps % 4):
            img = DocumentScanner.rotate_90(img, clockwise=True)

        # Giới hạn kích thước để tiết kiệm RAM trước khi tăng cường
        pil = Image.fromarray(img)
        long_side = max(pil.size)
        if long_side > DocumentScanner.MAX_LONG_SIDE:
            r = DocumentScanner.MAX_LONG_SIDE / long_side
            pil = pil.resize((int(pil.width * r), int(pil.height * r)), Image.Resampling.LANCZOS)
            img = np.asarray(pil)

        img = DocumentScanner.enhance_document(img, mode=mode)

        Image.fromarray(img).save(output_path, "JPEG", quality=92, optimize=True)
