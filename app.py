import sys
import os
import sqlite3
import json
import uuid
import shutil
from functools import partial
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTableWidget,
    QTableWidgetItem, QPushButton, QFileDialog, QLineEdit, QLabel, QMessageBox,
    QComboBox, QListWidget, QListWidgetItem, QDialog, QDialogButtonBox, QHeaderView,
    QScrollArea, QSystemTrayIcon, QMenu, QStyle
)
from PyQt5.QtCore import Qt

DB_NAME = "data.db"
CONFIG_NAME = "config.json"

# -------------------------
# 設定ファイル管理
# -------------------------
def load_settings():
    if os.path.exists(CONFIG_NAME):
        with open(CONFIG_NAME, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("upload_folder", None)
    return None

def save_settings(folder_path):
    with open(CONFIG_NAME, "w", encoding="utf-8") as f:
        json.dump({"upload_folder": folder_path}, f, ensure_ascii=False, indent=4)

def init_upload_folder():
    folder = load_settings()

    if folder is None:
        dlg = QFileDialog()
        dlg.setFileMode(QFileDialog.Directory)
        dlg.setOption(QFileDialog.ShowDirsOnly, True)
        QMessageBox.information(None, "保存先設定", "ファイル保存先フォルダを選択してください。")

        if dlg.exec_():
            folder = dlg.selectedFiles()[0]
            save_settings(folder)
        else:
            QMessageBox.warning(None, "エラー", "保存先が設定されていません。終了します。")
            sys.exit()

    os.makedirs(folder, exist_ok=True)

    # カテゴリフォルダ自動生成
    for cat in ["一般", "開発", "研究", "その他"]:
        os.makedirs(os.path.join(folder, cat), exist_ok=True)

    return folder



# -------------------------
# DB 初期化
# -------------------------
def get_db():
    return sqlite3.connect(DB_NAME)

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            start_date TEXT,
            owner TEXT,
            status TEXT,
            category TEXT,
            memo TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            filename TEXT,
            filepath TEXT,
            FOREIGN KEY(project_id) REFERENCES projects(id)
        )
    """)

    conn.commit()
    conn.close()

# -------------------------
# ファイル削除ダイアログ
# -------------------------
class FileDeleteDialog(QDialog):
    def __init__(self, project_id, parent=None):
        super().__init__(parent)
        self.setWindowTitle("削除するファイルを選択")
        self.resize(400, 300)
        self.project_id = project_id

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.file_list_widget = QListWidget()

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, filename FROM files WHERE project_id=?", (project_id,))
        self.files = cursor.fetchall()
        conn.close()

        for f in self.files:
            item = QListWidgetItem(f"{f[0]}: {f[1]}")
            item.setCheckState(Qt.Unchecked)
            self.file_list_widget.addItem(item)

        layout.addWidget(self.file_list_widget)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def get_selected_file_ids(self):
        selected_ids = []
        for i in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(i)
            if item.checkState() == Qt.Checked:
                selected_ids.append(int(item.text().split(":")[0]))
        return selected_ids

# -------------------------
# メイン画面
# -------------------------
class ProjectManager(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("企画管理アプリ")
        self.resize(1200, 800)

        self.categories = ["一般", "開発", "研究", "その他"]
        self.current_category = self.categories[0]

        main_layout = QVBoxLayout(self)

        # --- 検索 ---
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("検索（企画名・責任者・ステータス）")
        search_btn = QPushButton("検索")
        search_btn.clicked.connect(self.search_projects)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(search_btn)
        main_layout.addLayout(search_layout)

        # --- カテゴリー ---
        cat_layout = QHBoxLayout()
        cat_layout.addWidget(QLabel("カテゴリー:"))
        self.category_combo = QComboBox()
        self.category_combo.addItems(self.categories)
        self.category_combo.currentTextChanged.connect(self.change_category)
        cat_layout.addWidget(self.category_combo)
        main_layout.addLayout(cat_layout)

        # --- テーブル ---
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["ID","企画名","開始日","責任者","ファイル","進行状況・操作","メモ"])
        self.table.cellChanged.connect(self.memo_cell_changed)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0,60)
        for i in range(1,6):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        header.setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(80)
        main_layout.addWidget(self.table)

        # --- 追加フォーム ---
        form_layout = QHBoxLayout()
        self.title_input = QLineEdit(); self.title_input.setPlaceholderText("企画名")
        self.date_input = QLineEdit(); self.date_input.setPlaceholderText("開始日")
        self.owner_input = QLineEdit(); self.owner_input.setPlaceholderText("責任者")
        self.status_input = QComboBox(); self.status_input.addItems(["未開始","進行中","完了"])
        self.memo_input = QLineEdit(); self.memo_input.setPlaceholderText("メモ")
        add_btn = QPushButton("企画追加"); add_btn.clicked.connect(self.add_project)

        for w,label in zip(
            [self.title_input,self.date_input,self.owner_input,self.status_input,self.memo_input],
            ["企画名:","開始日:","責任者:","状態:","メモ:"]
        ):
            form_layout.addWidget(QLabel(label))
            form_layout.addWidget(w)

        form_layout.addWidget(add_btn)
        main_layout.addLayout(form_layout)

        self.load_projects()

    # -------------------------
    # DB 読み込み
    # -------------------------
    def load_projects(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM projects WHERE category=?", (self.current_category,))
        projects = cursor.fetchall()

        for row_idx, p in enumerate(projects):
            self.table.insertRow(row_idx)
            pid = p[0]

            # ID, タイトル, 開始日, 責任者
            for col, val in enumerate([pid, p[1], p[2] or "", p[3] or ""]):
                item = QTableWidgetItem(str(val))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_idx, col, item)

            # ファイル一覧
            files_widget = QWidget()
            v_layout = QVBoxLayout(files_widget)

            cursor.execute("SELECT id, filename FROM files WHERE project_id=?", (pid,))
            files = cursor.fetchall()

            for fid, fname in files:
                lbl = QLabel(f"<a href='#'>{fid}: {fname}</a>")
                lbl.setOpenExternalLinks(False)
                lbl.linkActivated.connect(partial(self.open_file, fid))
                v_layout.addWidget(lbl)

            v_layout.addStretch()
            scroll_files = QScrollArea()
            scroll_files.setWidgetResizable(True)
            scroll_files.setWidget(files_widget)
            scroll_files.setMaximumHeight(100)
            self.table.setCellWidget(row_idx, 4, scroll_files)

            # 状態＋操作
            container = QWidget()
            h_layout = QHBoxLayout()

            status_combo = QComboBox()
            status_combo.addItems(["未開始","進行中","完了"])
            status_combo.setCurrentText(p[4])
            status_combo.currentTextChanged.connect(partial(self.update_status, pid))
            h_layout.addWidget(status_combo)

            for btn_text, func in [
                ("ファイル追加", self.add_file),
                ("ファイル削除", self.delete_file),
                ("企画削除", self.delete_project)
            ]:
                btn = QPushButton(btn_text)
                btn.setMinimumWidth(120)
                btn.setMinimumHeight(30)
                btn.clicked.connect(partial(func, pid))
                h_layout.addWidget(btn)

            container.setLayout(h_layout)
            self.table.setCellWidget(row_idx, 5, container)

            # メモ
            memo_item = QTableWidgetItem(p[6] or "")
            memo_item.setFlags(memo_item.flags() | Qt.ItemIsEditable)
            self.table.setItem(row_idx, 6, memo_item)

        conn.close()
        self.table.blockSignals(False)

    # -------------------------
    # メモ自動保存
    # -------------------------
    def memo_cell_changed(self, row, column):
        if column != 6:
            return

        project_id_item = self.table.item(row, 0)
        memo_item = self.table.item(row, column)

        if project_id_item is None or memo_item is None:
            return

        project_id = int(project_id_item.text())
        memo_text = memo_item.text()

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE projects SET memo=? WHERE id=?", (memo_text, project_id))
        conn.commit()
        conn.close()

    # -------------------------
    # 状態更新
    # -------------------------
    def update_status(self, project_id, status):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE projects SET status=? WHERE id=?", (status, project_id))
        conn.commit()
        conn.close()

    # -------------------------
    # 企画追加
    # -------------------------
    def add_project(self):
        title = self.title_input.text()
        start = self.date_input.text()
        owner = self.owner_input.text()
        status = self.status_input.currentText()
        memo = self.memo_input.text()
        category = self.category_combo.currentText()

        if not title:
            QMessageBox.warning(self, "エラー", "企画名は必須です")
            return

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO projects (title, start_date, owner, status, category, memo)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (title, start, owner, status, category, memo))
        conn.commit()
        conn.close()

        self.title_input.clear()
        self.date_input.clear()
        self.owner_input.clear()
        self.memo_input.clear()

        self.load_projects()

    # -------------------------
    # ファイル追加（UUID＋相対パス）
    # -------------------------
    def add_file(self, project_id):
        files, _ = QFileDialog.getOpenFileNames(self, "ファイル選択")
        if not files:
            return

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT category FROM projects WHERE id=?", (project_id,))
        result = cursor.fetchone()
        category = result[0] if result else "その他"

        category_folder = os.path.join(UPLOAD_FOLDER, category)
        os.makedirs(category_folder, exist_ok=True)

        for f in files:
            original_name = os.path.basename(f)
            unique_name = f"{uuid.uuid4()}_{original_name}"
            save_path = os.path.join(category_folder, unique_name)

            shutil.copy(f, save_path)

            rel_path = os.path.relpath(save_path, start=os.getcwd())

            cursor.execute("""
                INSERT INTO files (project_id, filename, filepath)
                VALUES (?, ?, ?)
            """, (project_id, original_name, rel_path))

        conn.commit()
        conn.close()
        self.load_projects()

    # -------------------------
    # ファイル削除（例外安全）
    # -------------------------
    def delete_file(self, project_id):
        dlg = FileDeleteDialog(project_id, self)
        if dlg.exec_():
            selected_ids = dlg.get_selected_file_ids()
            if not selected_ids:
                return

            conn = get_db()
            cursor = conn.cursor()

            for fid in selected_ids:
                cursor.execute("SELECT filepath FROM files WHERE id=?", (fid,))
                r = cursor.fetchone()

                if r:
                    rel_path = r[0]
                    abs_path = os.path.join(os.getcwd(), rel_path)

                    try:
                        if os.path.exists(abs_path):
                            os.remove(abs_path)
                    except Exception as e:
                        print("削除失敗:", e)

                cursor.execute("DELETE FROM files WHERE id=?", (fid,))

            conn.commit()
            conn.close()
            self.load_projects()

    # -------------------------
    # 企画削除
    # -------------------------
    def delete_project(self, project_id):
        reply = QMessageBox.question(self, "確認", "本当に削除しますか？", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.No:
            return

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT filepath FROM files WHERE project_id=?", (project_id,))
        files = cursor.fetchall()

        for f in files:
            rel_path = f[0]
            abs_path = os.path.join(os.getcwd(), rel_path)

            try:
                if os.path.exists(abs_path):
                    os.remove(abs_path)
            except Exception as e:
                print("削除失敗:", e)

        cursor.execute("DELETE FROM files WHERE project_id=?", (project_id,))
        cursor.execute("DELETE FROM projects WHERE id=?", (project_id,))
        conn.commit()
        conn.close()

        self.load_projects()

    # -------------------------
    # ファイルを開く（相対パス対応）
    # -------------------------
    def open_file(self, file_id):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT filepath FROM files WHERE id=?", (file_id,))
        r = cursor.fetchone()
        conn.close()

        if r:
            rel_path = r[0]
            abs_path = os.path.join(os.getcwd(), rel_path)

            if os.path.exists(abs_path):
                os.startfile(abs_path)
            else:
                QMessageBox.warning(self, "エラー", "ファイルが存在しません")

    # -------------------------
    # 検索
    # -------------------------
    def search_projects(self):
        text = self.search_input.text().lower()
        self.table.blockSignals(True)
        self.table.setRowCount(0)

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM projects WHERE category=?", (self.current_category,))
        projects = cursor.fetchall()

        for p in projects:
            if text in (p[1] or "").lower() or text in (p[3] or "").lower() or text in (p[4] or "").lower():
                row_idx = self.table.rowCount()
                self.table.insertRow(row_idx)

                for col, val in enumerate([p[0], p[1], p[2] or "", p[3] or ""]):
                    item = QTableWidgetItem(str(val))
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.table.setItem(row_idx, col, item)

                files_widget = QWidget()
                v_layout = QVBoxLayout(files_widget)

                cursor.execute("SELECT id, filename FROM files WHERE project_id=?", (p[0],))
                files = cursor.fetchall()

                for f in files:
                    lbl = QLabel(f"{f[0]}: {f[1]}")
                    lbl.setStyleSheet("border:1px solid #ccc; padding:2px;")
                    v_layout.addWidget(lbl)

                v_layout.addStretch()
                scroll_files = QScrollArea()
                scroll_files.setWidgetResizable(True)
                scroll_files.setWidget(files_widget)
                scroll_files.setMaximumHeight(100)
                self.table.setCellWidget(row_idx, 4, scroll_files)

                container = QWidget()
                h_layout = QHBoxLayout()

                status_combo = QComboBox()
                status_combo.addItems(["未開始","進行中","完了"])
                status_combo.setCurrentText(p[4])
                status_combo.currentTextChanged.connect(partial(self.update_status, p[0]))
                h_layout.addWidget(status_combo)

                for btn_text, func in [
                    ("ファイル追加", self.add_file),
                    ("ファイル削除", self.delete_file),
                    ("企画削除", self.delete_project)
                ]:
                    btn = QPushButton(btn_text)
                    btn.setMinimumWidth(120)
                    btn.setMinimumHeight(30)
                    btn.clicked.connect(partial(func, p[0]))
                    h_layout.addWidget(btn)

                container.setLayout(h_layout)
                self.table.setCellWidget(row_idx, 5, container)

                memo_item = QTableWidgetItem(p[6] or "")
                memo_item.setFlags(memo_item.flags() | Qt.ItemIsEditable)
                self.table.setItem(row_idx, 6, memo_item)

        conn.close()
        self.table.blockSignals(False)

    # -------------------------
    # カテゴリー変更
    # -------------------------
    def change_category(self, text):
        self.current_category = text
        self.load_projects()


# -------------------------
# タスクトレイ
# -------------------------
class TrayApp:
    def __init__(self, window):
        self.window = window
        icon = self.window.style().standardIcon(QStyle.SP_ComputerIcon)
        self.tray_icon = QSystemTrayIcon(icon)
        self.tray_icon.setToolTip("企画管理アプリ")

        menu = QMenu()
        menu.addAction("開く", self.show_window)
        menu.addAction("終了", self.exit_app)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.show()

    def show_window(self):
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def exit_app(self):
        sys.exit()

# -------------------------
# 実行
# -------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    UPLOAD_FOLDER = init_upload_folder()
    init_db()
    window = ProjectManager()
    tray_app = TrayApp(window)
    window.showMaximized()
    sys.exit(app.exec_())
