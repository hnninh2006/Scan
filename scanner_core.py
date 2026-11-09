import cv2
import numpy as np

class DocumentScanner:
    @staticmethod
    def order_points(pts):
        """Sắp xếp 4 góc của tờ giấy theo thứ tự: trên-trái, trên-phải, dưới-phải, dưới-trái."""
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]

        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        return rect

    @staticmethod
    def four_point_transform(image, pts):
        """Biến đổi phối cảnh (cắt theo khung giấy và chỉnh thẳng góc nghiêng)."""
        rect = DocumentScanner.order_points(pts)
        (tl, tr, br, bl) = rect

        widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
        widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
        maxWidth = max(int(widthA), int(widthB))

        heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
        heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
        maxHeight = max(int(heightA), int(heightB))

        dst = np.array([
            [0, 0],
            [maxWidth - 1, 0],
            [maxWidth - 1, maxHeight - 1],
            [0, maxHeight - 1]], dtype="float32")

        M = cv2.getPerspectiveTransform(rect, dst)
        warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
        return warped

    @staticmethod
    def auto_crop_document(image: np.ndarray) -> np.ndarray:
        """
        Tự động nhận diện mép giấy và cắt phẳng.
        Nếu nền phức tạp không tìm thấy đủ 4 góc rõ ràng, giữ nguyên ảnh gốc để tránh cắt mất chữ.
        """
        orig = image.copy()
        h, w = image.shape[:2]
        ratio = h / 500.0
        resized = cv2.resize(image, (int(w / ratio), 500))

        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edged = cv2.Canny(blurred, 50, 150)

        # Làm dày cạnh để nối các nét đứt ở mép giấy
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        edged = cv2.dilate(edged, kernel, iterations=1)

        cnts, _ = cv2.findContours(edged.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        cnts = sorted(cnts, key=cv2.contourArea, reverse=True)[:5]

        screenCnt = None
        total_area = resized.shape[0] * resized.shape[1]

        for c in cnts:
            area = cv2.contourArea(c)
            # Chỉ nhận diện nếu diện tích tờ giấy lớn hơn 25% khung hình
            if area < total_area * 0.25:
                continue
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            if len(approx) == 4:
                screenCnt = approx
                break

        if screenCnt is not None:
            warped = DocumentScanner.four_point_transform(orig, screenCnt.reshape(4, 2) * ratio)
            return warped
        return orig

    @staticmethod
    def enhance_document(image: np.ndarray, mode: str = "color", contrast: float = 1.25) -> np.ndarray:
        """
        Tăng độ tương phản làm rõ chữ.
        mode = 'color': Giữ màu dấu đỏ, tăng độ nét và tương phản nền giấy.
        mode = 'bw': Chế độ đen trắng rõ chữ cho tài liệu văn bản.
        """
        if mode == "bw":
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            # Khử nhiễu nhẹ nhưng giữ sắc nét cạnh chữ
            denoised = cv2.GaussianBlur(gray, (3, 3), 0)
            bw = cv2.adaptiveThreshold(
                denoised, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 21, 10
            )
            return cv2.cvtColor(bw, cv2.COLOR_GRAY2BGR)
        else:
            # Chế độ màu: Cân bằng sáng cục bộ bằng không gian màu LAB (giữ nguyên màu con dấu đỏ)
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            cl = clahe.apply(l)
            merged = cv2.merge((cl, a, b))
            enhanced = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
            # Tăng nhẹ độ tương phản
            enhanced = cv2.convertScaleAbs(enhanced, alpha=contrast, beta=5)
            return enhanced

    @staticmethod
    def rotate_90(image: np.ndarray, clockwise: bool = True) -> np.ndarray:
        """Xoay ảnh 90 độ."""
        if clockwise:
            return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)

    @staticmethod
    def process_file(input_path: str, output_path: str, auto_crop: bool = True, mode: str = "color", rotate_steps: int = 0):
        """Đọc ảnh, áp dụng chuỗi xử lý (cắt mép -> xoay -> làm rõ chữ) và lưu ra file chất lượng cao."""
        # Hỗ trợ đọc đường dẫn tiếng Việt có dấu trên Windows/Android
        img_array = np.fromfile(input_path, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"Không thể đọc được file ảnh: {input_path}")

        if auto_crop:
            img = DocumentScanner.auto_crop_document(img)

        for _ in range(rotate_steps % 4):
            img = DocumentScanner.rotate_90(img, clockwise=True)

        img = DocumentScanner.enhance_document(img, mode=mode)

        # Lưu JPEG với chất lượng 92% (đảm bảo chữ cực kỳ sắc nét và dung lượng hợp lý)
        success, encoded_img = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        if not success:
            raise IOError("Lỗi khi mã hóa ảnh lưu trữ.")
        encoded_img.tofile(output_path)