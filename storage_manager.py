import os
import json
import shutil
from datetime import datetime
from pathlib import Path

class StorageManager:
    def __init__(self, base_dir=None):
        # Lưu dữ liệu cục bộ trong thư mục người dùng (tương thích Windows, Android, iOS)
        if base_dir is None:
            self.base_dir = Path.home() / "LandScannerData"
        else:
            self.base_dir = Path(base_dir)
            
        self.session_dir = self.base_dir / "current_session"
        self.output_dir = self.base_dir / "exported_pdfs"
        self.state_file = self.session_dir / "session_state.json"
        
        self._init_directories()

    def _init_directories(self):
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if not self.state_file.exists():
            self._save_state({
                "ma_ho_so": "26784",
                "so_to": "",
                "so_thua": "",
                "pages": [] # Danh sách đường dẫn các ảnh đã lưu theo thứ tự
            })

    def _save_state(self, state_data: dict):
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state_data, f, ensure_ascii=False, indent=2)

    def load_state(self) -> dict:
        if not self.state_file.exists():
            self._init_directories()
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Lọc bỏ các file ảnh nếu bị xóa ngoài ý muốn
            valid_pages = [p for p in data.get("pages", []) if os.path.exists(p)]
            data["pages"] = valid_pages
            return data
        except Exception:
            self._init_directories()
            return self.load_state()

    def add_page(self, temp_image_path: str) -> str:
        """Lưu một trang mới vào phiên làm việc hiện tại."""
        state = self.load_state()
        page_index = len(state["pages"]) + 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dest_filename = f"page_{page_index:03d}_{timestamp}.jpg"
        dest_path = str(self.session_dir / dest_filename)
        
        shutil.copy2(temp_image_path, dest_path)
        state["pages"].append(dest_path)
        self._save_state(state)
        return dest_path

    def replace_page(self, index: int, new_temp_image_path: str) -> str:
        """Chụp lại / Ghi đè một trang cụ thể theo đúng vị trí."""
        state = self.load_state()
        if 0 <= index < len(state["pages"]):
            old_path = state["pages"][index]
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except OSError:
                    pass
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            dest_filename = f"page_{index+1:03d}_{timestamp}.jpg"
            dest_path = str(self.session_dir / dest_filename)
            shutil.copy2(new_temp_image_path, dest_path)
            state["pages"][index] = dest_path
            self._save_state(state)
            return dest_path
        raise IndexError("Vị trí trang không hợp lệ.")

    def delete_page(self, index: int):
        """Xóa một trang khỏi danh sách."""
        state = self.load_state()
        if 0 <= index < len(state["pages"]):
            removed_path = state["pages"].pop(index)
            if os.path.exists(removed_path):
                try:
                    os.remove(removed_path)
                except OSError:
                    pass
            self._save_state(state)

    def update_metadata(self, ma_ho_so: str, so_to: str, so_thua: str):
        state = self.load_state()
        state["ma_ho_so"] = str(ma_ho_so).strip()
        state["so_to"] = str(so_to).strip()
        state["so_thua"] = str(so_thua).strip()
        self._save_state(state)

    def clear_session(self):
        """Xóa toàn bộ ảnh gốc khi người dùng chủ động bấm Xóa hồ sơ để làm bộ mới."""
        if self.session_dir.exists():
            shutil.rmtree(self.session_dir, ignore_errors=True)
        self._init_directories()