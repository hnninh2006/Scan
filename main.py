import os
import sys
import subprocess
import tempfile
import cv2
import flet as ft

from storage_manager import StorageManager
from scanner_core import DocumentScanner
from pdf_exporter import PDFExporter


class LandScannerApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "Scan Hồ Sơ Đất Đai"
        self.page.theme_mode = ft.ThemeMode.LIGHT
        # Kích thước mô phỏng màn hình điện thoại khi chạy trên Windows
        self.page.window.width = 430
        self.page.window.height = 860
        self.page.padding = 12

        self.storage = StorageManager()
        self.state = self.storage.load_state()

        # Trạng thái ảnh đang chờ lưu (Preview trước khi nhấn LƯU ẢNH)
        self.raw_captured_path = None
        self.preview_processed_path = None
        self.current_rotation = 0
        self.current_mode = "color"     # 'color' hoặc 'bw'
        self.auto_crop_enabled = True
        self.retake_index = None        # None = chụp trang mới, int = đang chụp lại trang số X

        self._build_ui()
        self._refresh_gallery()

    def _build_ui(self):
        # 1. Thanh tiêu đề & Bộ đếm số trang
        self.lbl_page_count = ft.Text(
            f"Đã lưu: {len(self.state['pages'])} trang",
            size=16,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.BLUE_900
        )

        header = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.DOCUMENT_SCANNER, color=ft.Colors.BLUE_800, size=28),
                    ft.Text("SCAN HỒ SƠ ĐẤT ĐAI", size=18, weight=ft.FontWeight.BOLD, expand=True),
                    self.lbl_page_count
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN
            ),
            padding=ft.padding.symmetric(vertical=8, horizontal=10),
            bgcolor=ft.Colors.BLUE_50,
            border_radius=8
        )

        # 2. Khu vực hiển thị ảnh đang chụp / xem trước (Preview Area)
        self.img_preview = ft.Image(
            src="",
            fit=ft.ImageFit.CONTAIN,
            visible=False,
            expand=True
        )
        self.lbl_preview_hint = ft.Text(
            "Nhấn [CHỤP ẢNH] bên dưới để quét trang hồ sơ",
            color=ft.Colors.GREY_600,
            text_align=ft.TextAlign.CENTER
        )
        self.preview_box = ft.Container(
            content=ft.Stack(
                [
                    ft.Container(content=self.lbl_preview_hint, alignment=ft.alignment.center),
                    self.img_preview
                ]
            ),
            height=290,
            width=float("inf"),
            bgcolor=ft.Colors.GREY_200,
            border=ft.border.all(1, ft.Colors.GREY_400),
            border_radius=10,
            alignment=ft.alignment.center,
            padding=6
        )

        # 3. Thanh công cụ chỉnh sửa ảnh vừa chụp (Xoay 90, Chế độ Màu/Đen trắng, Cắt mép)
        self.sw_auto_crop = ft.Switch(
            label="Tự cắt mép",
            value=True,
            on_change=self._on_filter_changed
        )
        self.dd_mode = ft.Dropdown(
            width=135,
            value="color",
            options=[
                ft.dropdown.Option("color", "Màu (Rõ dấu)"),
                ft.dropdown.Option("bw", "Đen trắng")
            ],
            on_change=self._on_filter_changed,
            content_padding=6
        )
        self.btn_rotate = ft.IconButton(
            icon=ft.Icons.ROTATE_90_DEGREES_CW,
            tooltip="Xoay 90 độ",
            on_click=self._on_rotate_clicked,
            disabled=True
        )

        edit_toolbar = ft.Row(
            [self.sw_auto_crop, self.dd_mode, self.btn_rotate],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN
        )

        # 4. Danh sách ảnh thu nhỏ (Thumbnails) của các trang đã lưu
        self.gallery_row = ft.Row(scroll=ft.ScrollMode.AUTO, spacing=10)
        self.gallery_container = ft.Container(
            content=self.gallery_row,
            height=145,
            padding=6,
            bgcolor=ft.Colors.GREY_100,
            border_radius=8
        )

        # 5. Các nút thao tác chính (Thiết kế nút to, dễ bấm bằng 1 tay)
        self.btn_capture = ft.ElevatedButton(
            text="CHỤP ẢNH (CAMERA)",
            icon=ft.Icons.CAMERA_ALT,
            bgcolor=ft.Colors.BLUE_700,
            color=ft.Colors.WHITE,
            height=50,
            expand=True,
            on_click=self._on_capture_camera
        )

        self.btn_pick_file = ft.IconButton(
            icon=ft.Icons.PHOTO_LIBRARY,
            tooltip="Chọn ảnh từ máy / Camera hệ thống",
            bgcolor=ft.Colors.BLUE_100,
            height=50,
            width=50,
            on_click=lambda _: self.file_picker.pick_files(
                allow_multiple=False,
                file_type=ft.FilePickerFileType.IMAGE
            )
        )

        self.btn_save_page = ft.ElevatedButton(
            text="LƯU ẢNH",
            icon=ft.Icons.CHECK_CIRCLE,
            bgcolor=ft.Colors.GREEN_700,
            color=ft.Colors.WHITE,
            height=48,
            expand=True,
            disabled=True,
            on_click=self._on_save_page
        )

        self.btn_retake_current = ft.OutlinedButton(
            text="CHỤP LẠI",
            icon=ft.Icons.REFRESH,
            height=48,
            expand=True,
            disabled=True,
            on_click=self._on_capture_camera
        )

        self.btn_view_list = ft.OutlinedButton(
            text="XEM DANH SÁCH ẢNH",
            icon=ft.Icons.VIEW_LIST,
            height=44,
            expand=True,
            on_click=self._open_full_list_dialog
        )

        self.btn_clear_all = ft.OutlinedButton(
            text="HỒ SƠ MỚI",
            icon=ft.Icons.DELETE_SWEEP,
            height=44,
            on_click=self._confirm_clear_session
        )

        self.btn_export_pdf = ft.ElevatedButton(
            text="CHUYỂN THÀNH PDF",
            icon=ft.Icons.PICTURE_AS_PDF,
            bgcolor=ft.Colors.RED_700,
            color=ft.Colors.WHITE,
            height=54,
            width=float("inf"),
            on_click=self._open_export_pdf_dialog
        )

        # FilePicker hỗ trợ chọn ảnh & chọn thư mục lưu PDF
        self.file_picker = ft.FilePicker(on_result=self._on_file_picked)
        self.dir_picker = ft.FilePicker(on_result=self._on_dir_picked)
        self.page.overlay.extend([self.file_picker, self.dir_picker])

        # Ghép toàn bộ bố cục lên màn hình chính
        self.page.add(
            header,
            self.preview_box,
            edit_toolbar,
            ft.Row([self.btn_capture, self.btn_pick_file]),
            ft.Row([self.btn_save_page, self.btn_retake_current]),
            ft.Text("Danh sách trang đã scan (Giữ đúng thứ tự PDF):", size=13, weight=ft.FontWeight.W_600),
            self.gallery_container,
            ft.Row([self.btn_view_list, self.btn_clear_all]),
            self.btn_export_pdf
        )

    # ================= XỬ LÝ CAMERA & CHỤP ẢNH =================
    def _on_capture_camera(self, e):
        """
        Mở Camera trực tiếp để chụp tài liệu.
        Hỗ trợ phím SPACE hoặc click chuột để chụp, phím ESC để thoát.
        Nếu thiết bị không mở được OpenCV VideoCapture trực tiếp, tự động chuyển sang Camera hệ thống.
        """
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            self._show_snack("Không thể truy cập trực tiếp phần cứng Camera. Đang mở trình chọn ảnh/Camera hệ thống...", is_error=True)
            self.file_picker.pick_files(allow_multiple=False, file_type=ft.FilePickerFileType.IMAGE)
            return

        # Thiết lập độ phân giải cao cho Camera (Full HD nếu hỗ trợ)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

        captured_frame = None
        win_name = "CAMERA SCAN - Nhan SPACE de chup / ESC de huy"
        cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            display_frame = frame.copy()
            h, w = display_frame.shape[:2]
            # Vẽ khung căn chỉnh giấy A4 trên màn hình Camera
            cv2.rectangle(display_frame, (int(w*0.08), int(h*0.06)), (int(w*0.92), int(h*0.94)), (0, 255, 0), 2)
            cv2.putText(
                display_frame,
                "Nhan [SPACE] hoac [ENTER] de chup - [ESC] de thoat",
                (20, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2
            )

            cv2.imshow(win_name, display_frame)
            key = cv2.waitKey(1) & 0xFF
            if key in [32, 13]:  # Phím Space hoặc Enter
                captured_frame = frame
                break
            elif key == 27:      # Phím ESC
                break

        cap.release()
        cv2.destroyAllWindows()

        if captured_frame is not None:
            temp_raw = os.path.join(tempfile.gettempdir(), "raw_capture_land.jpg")
            # Ghi file an toàn với đường dẫn Unicode
            _, buf = cv2.imencode(".jpg", captured_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            buf.tofile(temp_raw)
            self._load_captured_image(temp_raw)

    def _on_file_picked(self, e: ft.FilePickerResultEvent):
        if e.files and len(e.files) > 0:
            picked_path = e.files[0].path
            if picked_path and os.path.exists(picked_path):
                self._load_captured_image(picked_path)
            else:
                self._show_snack("Ảnh không hợp lệ hoặc không có quyền đọc file.", is_error=True)

    def _load_captured_image(self, raw_path: str):
        self.raw_captured_path = raw_path
        self.current_rotation = 0
        self._apply_preview_processing()

    def _apply_preview_processing(self):
        if not self.raw_captured_path or not os.path.exists(self.raw_captured_path):
            return
        try:
            temp_out = os.path.join(
                tempfile.gettempdir(),
                f"preview_processed_{os.urandom(3).hex()}.jpg"
            )
            DocumentScanner.process_file(
                input_path=self.raw_captured_path,
                output_path=temp_out,
                auto_crop=self.sw_auto_crop.value,
                mode=self.dd_mode.value,
                rotate_steps=self.current_rotation
            )
            # Xóa file preview cũ nếu có
            if self.preview_processed_path and os.path.exists(self.preview_processed_path):
                try:
                    os.remove(self.preview_processed_path)
                except OSError:
                    pass

            self.preview_processed_path = temp_out
            self.img_preview.src = self.preview_processed_path
            self.img_preview.visible = True
            self.lbl_preview_hint.visible = False

            self.btn_save_page.disabled = False
            self.btn_retake_current.disabled = False
            self.btn_rotate.disabled = False

            if self.retake_index is not None:
                self.btn_save_page.text = f"CẬP NHẬT TRANG {self.retake_index + 1}"
            else:
                self.btn_save_page.text = "LƯU ẢNH"

            self.page.update()
        except Exception as ex:
            self._show_snack(f"Lỗi xử lý ảnh: {str(ex)}", is_error=True)

    def _on_filter_changed(self, e):
        if self.raw_captured_path:
            self._apply_preview_processing()

    def _on_rotate_clicked(self, e):
        if self.raw_captured_path:
            self.current_rotation = (self.current_rotation + 1) % 4
            self._apply_preview_processing()

    # ================= LƯU, XÓA, CHỤP LẠI TRANG =================
    def _on_save_page(self, e):
        if not self.preview_processed_path or not os.path.exists(self.preview_processed_path):
            self._show_snack("Chưa có ảnh để lưu!", is_error=True)
            return

        try:
            if self.retake_index is not None:
                self.storage.replace_page(self.retake_index, self.preview_processed_path)
                self._show_snack(f"Đã cập nhật lại Trang {self.retake_index + 1} thành công.")
                self.retake_index = None
            else:
                self.storage.add_page(self.preview_processed_path)
                page_num = len(self.storage.load_state()["pages"])
                self._show_snack(f"Đã lưu Trang {page_num}.")

            # Reset vùng preview để sẵn sàng chụp trang tiếp theo
            self.raw_captured_path = None
            self.img_preview.visible = False
            self.lbl_preview_hint.visible = True
            self.lbl_preview_hint.value = "Đã lưu! Nhấn [CHỤP ẢNH] để chụp trang tiếp theo."
            self.btn_save_page.disabled = True
            self.btn_save_page.text = "LƯU ẢNH"
            self.btn_retake_current.disabled = True
            self.btn_rotate.disabled = True

            self._refresh_gallery()
        except Exception as ex:
            self._show_snack(f"Lỗi khi lưu trang: {str(ex)}", is_error=True)

    def _refresh_gallery(self):
        self.state = self.storage.load_state()
        pages = self.state["pages"]
        self.lbl_page_count.value = f"Đã lưu: {len(pages)} trang"
        self.gallery_row.controls.clear()

        for idx, img_path in enumerate(pages):
            card = ft.Container(
                content=ft.Column(
                    [
                        ft.Text(f"Trang {idx + 1}", size=12, weight=ft.FontWeight.BOLD),
                        ft.Image(src=img_path, width=75, height=75, fit=ft.ImageFit.COVER, border_radius=4),
                        ft.Row(
                            [
                                ft.IconButton(
                                    icon=ft.Icons.CAMERA_ALT_OUTLINED,
                                    icon_size=16,
                                    tooltip=f"Chụp lại trang {idx + 1}",
                                    on_click=lambda e, i=idx: self._start_retake_page(i)
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.DELETE_OUTLINE,
                                    icon_size=16,
                                    icon_color=ft.Colors.RED_600,
                                    tooltip=f"Xóa trang {idx + 1}",
                                    on_click=lambda e, i=idx: self._delete_page(i)
                                ),
                            ],
                            spacing=0,
                            alignment=ft.MainAxisAlignment.CENTER
                        )
                    ],
                    spacing=2,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER
                ),
                padding=4,
                bgcolor=ft.Colors.WHITE,
                border=ft.border.all(1, ft.Colors.GREY_300),
                border_radius=6
            )
            self.gallery_row.controls.append(card)

        self.page.update()

    def _start_retake_page(self, index: int):
        self.retake_index = index
        self.lbl_preview_hint.visible = True
        self.img_preview.visible = False
        self.lbl_preview_hint.value = f"Đang ở chế độ CHỤP LẠI Trang {index + 1}.\nHãy nhấn [CHỤP ẢNH] hoặc chọn ảnh mới."
        self._show_snack(f"Hãy chụp ảnh mới để thay thế cho Trang {index + 1}")
        self.page.update()

    def _delete_page(self, index: int):
        self.storage.delete_page(index)
        if self.retake_index == index:
            self.retake_index = None
        self._refresh_gallery()
        self._show_snack(f"Đã xóa Trang {index + 1}. Thứ tự các trang sau đã tự động cập nhật.")

    def _open_full_list_dialog(self, e):
        pages = self.storage.load_state()["pages"]
        if not pages:
            self._show_snack("Chưa có trang nào trong danh sách.", is_error=True)
            return

        list_view = ft.ListView(spacing=10, height=400, width=350)
        for idx, path in enumerate(pages):
            list_view.controls.append(
                ft.ListTile(
                    leading=ft.Image(src=path, width=50, height=65, fit=ft.ImageFit.COVER),
                    title=ft.Text(f"Trang {idx + 1}: Ảnh thứ {idx + 1}", weight=ft.FontWeight.BOLD),
                    subtitle=ft.Text(os.path.basename(path), size=11),
                    trailing=ft.IconButton(
                        icon=ft.Icons.DELETE,
                        icon_color=ft.Colors.RED_700,
                        on_click=lambda ev, i=idx: (
                            self._delete_page(i),
                            self.page.close(dlg)
                        )
                    )
                )
            )

        dlg = ft.AlertDialog(
            title=ft.Text(f"Danh sách trang đã scan ({len(pages)} trang)"),
            content=list_view,
            actions=[ft.TextButton("Đóng", on_click=lambda _: self.page.close(dlg))]
        )
        self.page.open(dlg)

    def _confirm_clear_session(self, e):
        def _do_clear(_):
            self.storage.clear_session()
            self.retake_index = None
            self.raw_captured_path = None
            self.img_preview.visible = False
            self.lbl_preview_hint.visible = True
            self.lbl_preview_hint.value = "Đã tạo phiên hồ sơ mới. Nhấn [CHỤP ẢNH] để bắt đầu."
            self._refresh_gallery()
            self.page.close(dlg)
            self._show_snack("Đã xóa dữ liệu tạm và tạo hồ sơ mới.")

        dlg = ft.AlertDialog(
            title=ft.Text("Xác nhận xóa hồ sơ đang chụp"),
            content=ft.Text("Bạn có chắc chắn muốn xóa toàn bộ các trang ảnh gốc hiện tại để bắt đầu chụp bộ hồ sơ mới không?"),
            actions=[
                ft.TextButton("Hủy", on_click=lambda _: self.page.close(dlg)),
                ft.ElevatedButton("Xóa & Tạo mới", bgcolor=ft.Colors.RED_600, color=ft.Colors.WHITE, on_click=_do_clear)
            ]
        )
        self.page.open(dlg)

    # ================= BIỂU MẪU NHẬP THÔNG TIN & XUẤT PDF =================
    def _open_export_pdf_dialog(self, e):
        state = self.storage.load_state()
        if not state["pages"]:
            self._show_snack("Vui lòng chụp và lưu ít nhất 1 trang trước khi chuyển thành PDF!", is_error=True)
            return

        self.selected_output_dir = str(self.storage.output_dir)

        self.tf_ma_ho_so = ft.TextField(
            label="Mã hồ sơ",
            value=state.get("ma_ho_so") or "26784",
            keyboard_type=ft.KeyboardType.TEXT,
            on_change=self._update_filename_preview
        )
        self.tf_so_to = ft.TextField(
            label="Số tờ bản đồ (*)",
            value=state.get("so_to", ""),
            hint_text="Ví dụ: 12",
            keyboard_type=ft.KeyboardType.NUMBER,
            on_change=self._update_filename_preview
        )
        self.tf_so_thua = ft.TextField(
            label="Số thứ tự thửa đất (*)",
            value=state.get("so_thua", ""),
            hint_text="Ví dụ: 35",
            keyboard_type=ft.KeyboardType.NUMBER,
            on_change=self._update_filename_preview
        )

        self.lbl_filename_preview = ft.Text(
            value="",
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.BLUE_800,
            size=13
        )
        self.lbl_folder_path = ft.Text(
            value=f"Thư mục lưu: {self.selected_output_dir}",
            size=11,
            color=ft.Colors.GREY_700
        )

        self._update_filename_preview(None)

        btn_choose_dir = ft.OutlinedButton(
            text="Chọn thư mục lưu PDF",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=lambda _: self.dir_picker.get_directory_path()
        )

        self.export_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Nhập thông tin Hồ sơ Đất đai"),
            content=ft.Column(
                [
                    self.tf_ma_ho_so,
                    self.tf_so_to,
                    self.tf_so_thua,
                    ft.Divider(),
                    ft.Text("Tên file PDF sẽ tạo:", size=12),
                    self.lbl_filename_preview,
                    btn_choose_dir,
                    self.lbl_folder_path
                ],
                tight=True,
                spacing=10
            ),
            actions=[
                ft.TextButton("Quay lại", on_click=lambda _: self.page.close(self.export_dialog)),
                ft.ElevatedButton(
                    "XUẤT FILE PDF",
                    icon=ft.Icons.PICTURE_AS_PDF,
                    bgcolor=ft.Colors.RED_700,
                    color=ft.Colors.WHITE,
                    on_click=self._execute_pdf_export
                )
            ]
        )
        self.page.open(self.export_dialog)

    def _update_filename_preview(self, e):
        ma = self.tf_ma_ho_so.value.strip() or "[MÃ HỒ SƠ]"
        to = self.tf_so_to.value.strip() or "[SỐ TỜ]"
        thua = self.tf_so_thua.value.strip() or "[SỐ THỬA]"
        self.lbl_filename_preview.value = f"CHUACOGIAY_{ma}_{to}_{thua}.pdf"
        self.page.update()

    def _on_dir_picked(self, e: ft.FilePickerResultEvent):
        if e.path:
            self.selected_output_dir = e.path
            self.lbl_folder_path.value = f"Thư mục lưu: {self.selected_output_dir}"
            self.page.update()

    def _execute_pdf_export(self, e):
        ma = self.tf_ma_ho_so.value.strip()
        to = self.tf_so_to.value.strip()
        thua = self.tf_so_thua.value.strip()

        if not ma or not to or not thua:
            self._show_snack("Vui lòng nhập đầy đủ Mã hồ sơ, Số tờ bản đồ và Số thửa đất!", is_error=True)
            return

        # Lưu lại metadata để nếu thoát ra vào lại vẫn nhớ
        self.storage.update_metadata(ma, to, thua)
        pages = self.storage.load_state()["pages"]

        try:
            pdf_path = PDFExporter.export_images_to_pdf(
                image_paths=pages,
                output_folder=self.selected_output_dir,
                ma_ho_so=ma,
                so_to=to,
                so_thua=thua
            )
            self.page.close(self.export_dialog)
            self._show_export_success_dialog(pdf_path)
        except Exception as ex:
            self._show_snack(f"Xuất PDF thất bại: {str(ex)}", is_error=True)

    def _show_export_success_dialog(self, pdf_path: str):
        dlg = ft.AlertDialog(
            title=ft.Row([ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN_700), ft.Text("Xuất PDF Thành Công!")]),
            content=ft.Column(
                [
                    ft.Text("Đã ghép đầy đủ các trang theo đúng thứ tự."),
                    ft.Text(f"Tên file: {os.path.basename(pdf_path)}", weight=ft.FontWeight.BOLD),
                    ft.Text(f"Đường dẫn: {pdf_path}", size=12, selectable=True),
                    ft.Text("Lưu ý: Hồ sơ ảnh gốc vẫn được giữ lại an toàn cho đến khi bạn bấm [HỒ SƠ MỚI].", size=12, italic=True)
                ],
                tight=True,
                spacing=8
            ),
            actions=[
                ft.OutlinedButton("Mở xem PDF", icon=ft.Icons.OPEN_IN_NEW, on_click=lambda _: self._open_file_native(pdf_path)),
                ft.OutlinedButton("Mở thư mục / Chia sẻ Zalo", icon=ft.Icons.SHARE, on_click=lambda _: self._open_folder_native(pdf_path)),
                ft.ElevatedButton("Đóng", on_click=lambda _: self.page.close(dlg))
            ]
        )
        self.page.open(dlg)

    def _open_file_native(self, filepath: str):
        try:
            if sys.platform.startswith("win"):
                os.startfile(filepath)
            elif sys.platform == "darwin":
                subprocess.call(["open", filepath])
            else:
                subprocess.call(["xdg-open", filepath])
        except Exception as e:
            self._show_snack(f"Không thể tự mở file: {e}", is_error=True)

    def _open_folder_native(self, filepath: str):
        folder = os.path.dirname(filepath)
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(f'explorer /select,"{filepath}"')
            elif sys.platform == "darwin":
                subprocess.call(["open", folder])
            else:
                subprocess.call(["xdg-open", folder])
        except Exception as e:
            self._show_snack(f"Không thể mở thư mục: {e}", is_error=True)

    def _show_snack(self, message: str, is_error: bool = False):
        snack = ft.SnackBar(
            content=ft.Text(message, color=ft.Colors.WHITE),
            bgcolor=ft.Colors.RED_700 if is_error else ft.Colors.GREEN_800,
            duration=2500
        )
        self.page.open(snack)


def main(page: ft.Page):
    LandScannerApp(page)


if __name__ == "__main__":
    ft.app(target=main)