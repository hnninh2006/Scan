import os
from pathlib import Path
from PIL import Image, ImageOps

class PDFExporter:
    # Kích thước trang A4 chuẩn ở mật độ 150 DPI (1240 x 1754 pixels) - Đủ sắc nét để in và đọc, dung lượng nhẹ
    A4_WIDTH_PX = 1240
    A4_HEIGHT_PX = 1754
    MARGIN_PX = 36 # Lề trắng an toàn quanh mép giấy tránh mất nội dung khi in

    @staticmethod
    def build_filename(ma_ho_so: str, so_to: str, so_thua: str) -> str:
        """
        Quy tắc đặt tên bắt buộc:
        Ví dụ chuẩn trong yêu cầu: CHUACOGIAY_26784_12_35.pdf
        """
        ma = str(ma_ho_so).strip()
        to = str(so_to).strip()
        thua = str(so_thua).strip()

        if not ma or not to or not thua:
            raise ValueError("Vui lòng nhập đầy đủ Mã hồ sơ, Số tờ bản đồ và Số thứ tự thửa đất.")

        # Loại bỏ các ký tự không hợp lệ trong tên file hệ điều hành
        invalid_chars = '<>:"/\\|?*'
        for ch in invalid_chars:
            ma = ma.replace(ch, "")
            to = to.replace(ch, "")
            thua = thua.replace(ch, "")

        return f"CHUACOGIAY_{ma}_{to}_{thua}.pdf"

    @classmethod
    def export_images_to_pdf(cls, image_paths: list[str], output_folder: str, ma_ho_so: str, so_to: str, so_thua: str) -> str:
        if not image_paths:
            raise ValueError("Danh sách ảnh trống! Vui lòng chụp ít nhất 1 trang hồ sơ trước khi xuất PDF.")

        filename = cls.build_filename(ma_ho_so, so_to, so_thua)
        out_dir = Path(output_folder)
        out_dir.mkdir(parents=True, exist_ok=True)
        output_pdf_path = out_dir / filename

        pdf_pages = []

        for idx, img_path in enumerate(image_paths):
            if not os.path.exists(img_path):
                raise FileNotFoundError(f"Không tìm thấy ảnh trang {idx + 1} tại: {img_path}")

            try:
                with Image.open(img_path) as img:
                    # Tự động xoay theo EXIF của điện thoại nếu có
                    img = ImageOps.exif_transpose(img)
                    img_rgb = img.convert("RGB")
                    orig_w, orig_h = img_rgb.size

                    # Tự động chọn chiều trang A4 (Dọc hoặc Ngang) khớp với chiều của bản vẽ/trang hồ sơ
                    if orig_w > orig_h:
                        page_w, page_h = cls.A4_HEIGHT_PX, cls.A4_WIDTH_PX
                    else:
                        page_w, page_h = cls.A4_WIDTH_PX, cls.A4_HEIGHT_PX

                    # Tạo trang giấy trắng chuẩn A4
                    a4_canvas = Image.new("RGB", (page_w, page_h), (255, 255, 255))

                    # Tính toán tỷ lệ thu phóng giữ nguyên tỷ lệ khung hình (Aspect Ratio), trừ lề an toàn
                    avail_w = page_w - (2 * cls.MARGIN_PX)
                    avail_h = page_h - (2 * cls.MARGIN_PX)
                    scale = min(avail_w / orig_w, avail_h / orig_h)

                    new_w = max(1, int(orig_w * scale))
                    new_h = max(1, int(orig_h * scale))

                    resized_img = img_rgb.resize((new_w, new_h), Image.Resampling.LANCZOS)

                    # Căn giữa trang A4
                    offset_x = (page_w - new_w) // 2
                    offset_y = (page_h - new_h) // 2
                    a4_canvas.paste(resized_img, (offset_x, offset_y))

                    pdf_pages.append(a4_canvas)
            except Exception as e:
                raise RuntimeError(f"Lỗi khi xử lý trang {idx + 1}: {str(e)}")

        try:
            first_page = pdf_pages[0]
            rest_pages = pdf_pages[1:]
            first_page.save(
                str(output_pdf_path),
                "PDF",
                resolution=150.0,
                save_all=True,
                append_images=rest_pages
            )
        finally:
            for p in pdf_pages:
                p.close()

        return str(output_pdf_path)