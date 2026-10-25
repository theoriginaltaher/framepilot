from __future__ import annotations

from dataclasses import replace
import logging
import os
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, QSize, Signal
from PySide6.QtGui import QAction, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QScrollArea, QSlider, QSplitter, QStatusBar, QToolBar, QVBoxLayout, QWidget,
    QAbstractItemView,
)

from framepilot.culling import analyse_image, group_similar
from framepilot.culling.analyzer import suggested_status
from framepilot.imaging import PreviewDecoder, render_preview
from framepilot.imaging.renderer import export_jpeg
from framepilot.models import CullStatus, DevelopSettings, PhotoRecord
from framepilot.presets import get_preset, preset_names
from framepilot.services import discover_raw_files
from framepilot.storage import ProjectDatabase
from framepilot.ui.workers import FunctionWorker
from framepilot.xmp import export_sidecar

log = logging.getLogger(__name__)


def pil_to_pixmap(image) -> QPixmap:
    raw = image.convert("RGB").tobytes("raw", "RGB")
    qimage = QImage(raw, image.width, image.height, image.width * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimage.copy())


class MainWindow(QMainWindow):
    """Professional three-pane FramePilot workspace."""

    SETTINGS = [
        ("exposure", "Exposure", -500, 500, 100), ("temperature", "Temperature", 2000, 12000, 1),
        ("tint", "Tint", -150, 150, 1), ("contrast", "Contrast", -100, 100, 1),
        ("highlights", "Highlights", -100, 100, 1), ("shadows", "Shadows", -100, 100, 1),
        ("whites", "Whites", -100, 100, 1), ("blacks", "Blacks", -100, 100, 1),
        ("texture", "Texture", -100, 100, 1), ("clarity", "Clarity", -100, 100, 1),
        ("dehaze", "Dehaze", -100, 100, 1), ("vibrance", "Vibrance", -100, 100, 1),
        ("saturation", "Saturation", -100, 100, 1), ("sharpening", "Sharpening", 0, 150, 1),
        ("luminance_noise_reduction", "Noise reduction", 0, 100, 1),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FramePilot — Local RAW Workflow")
        self.resize(1540, 920)
        self.thread_pool = QThreadPool.globalInstance()
        self.decoder = PreviewDecoder()
        self.database: ProjectDatabase | None = None
        self.project_path: Path | None = None
        self.photos: list[PhotoRecord] = []
        self.current_photo: PhotoRecord | None = None
        self.original_preview = None
        self.clipboard_settings: DevelopSettings | None = None
        self.active_workers: list[FunctionWorker] = []
        self.history: dict[int, list[DevelopSettings]] = {}
        self.history_position: dict[int, int] = {}
        self._updating_controls = False
        self._build_ui()
        self._build_shortcuts()
        self.setStyleSheet(self._stylesheet())

    def _build_ui(self) -> None:
        toolbar = QToolBar("Workflow", self)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)
        self._action(toolbar, "Open folder", self.open_folder, "Ctrl+O")
        self._action(toolbar, "Create project", self.create_project, "Ctrl+Shift+N")
        self._action(toolbar, "Open project", self.open_project, "Ctrl+Shift+O")
        self._action(toolbar, "Save", self.save_project, "Ctrl+S")
        toolbar.addSeparator()
        self._action(toolbar, "Analyse", self.analyse_photos, "Ctrl+R")
        self._action(toolbar, "Export XMP", self.export_xmp_selected, "Ctrl+E")
        self._action(toolbar, "Export JPEG", self.export_jpeg_selected, "Ctrl+Shift+E")
        self._action(toolbar, "Clear cache", self.clear_cache)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        browser_host = QWidget(); browser_layout = QVBoxLayout(browser_host); browser_layout.setContentsMargins(0, 0, 0, 0)
        browser_controls = QHBoxLayout()
        self.filter_combo = QComboBox(); self.filter_combo.addItems(["All", "Keep", "Review", "Reject", "Unrated", "Rated"])
        self.filter_combo.currentTextChanged.connect(self._apply_filter)
        self.sort_combo = QComboBox(); self.sort_combo.addItems(["Filename", "Capture time", "Rating", "Quality"])
        self.sort_combo.currentTextChanged.connect(self._sort_changed)
        browser_controls.addWidget(QLabel("Show")); browser_controls.addWidget(self.filter_combo)
        browser_controls.addWidget(QLabel("Sort")); browser_controls.addWidget(self.sort_combo)
        browser_layout.addLayout(browser_controls)
        self.browser = QListWidget()
        self.browser.setViewMode(QListWidget.ViewMode.IconMode)
        self.browser.setIconSize(QSize(190, 135))
        self.browser.setGridSize(QSize(215, 190))
        self.browser.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.browser.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.browser.currentItemChanged.connect(self._photo_selected)
        browser_layout.addWidget(self.browser, 1)
        splitter.addWidget(browser_host)

        preview_host = QWidget()
        preview_layout = QVBoxLayout(preview_host)
        self.preview = QLabel("Open a RAW folder to begin")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(560, 420)
        self.preview.setStyleSheet("background:#111; color:#999; border:1px solid #292929")
        self.preview_scroll = QScrollArea(); self.preview_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_scroll.setWidgetResizable(True); self.preview_scroll.setWidget(self.preview)
        preview_layout.addWidget(self.preview_scroll, 1)
        zoom_row = QHBoxLayout(); zoom_row.addStretch()
        zoom_row.addWidget(QLabel("Zoom")); self.zoom_combo = QComboBox(); self.zoom_combo.addItems(["Fit", "100%"])
        self.zoom_combo.currentTextChanged.connect(self.refresh_preview); zoom_row.addWidget(self.zoom_combo)
        preview_layout.addLayout(zoom_row)
        self.preview_note = QLabel("Preview: approximate FramePilot rendering — Adobe output may differ")
        self.preview_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self.preview_note)
        splitter.addWidget(preview_host)

        panel_scroll = QScrollArea()
        panel_scroll.setWidgetResizable(True)
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        self.photo_info = QLabel("No photograph selected")
        self.photo_info.setWordWrap(True)
        panel_layout.addWidget(self.photo_info)
        self.before_after = QCheckBox("Show original (before)")
        self.before_after.toggled.connect(self.refresh_preview)
        panel_layout.addWidget(self.before_after)
        self.wb = QComboBox()
        self.wb.addItems(["As Shot", "Auto", "Custom"])
        self.wb.currentTextChanged.connect(self._wb_changed)
        panel_layout.addWidget(QLabel("White balance"))
        panel_layout.addWidget(self.wb)
        form = QFormLayout()
        self.sliders: dict[str, tuple[QSlider, QLabel, int]] = {}
        for name, label, low, high, scale in self.SETTINGS:
            row = QWidget(); layout = QHBoxLayout(row); layout.setContentsMargins(0, 0, 0, 0)
            slider = QSlider(Qt.Orientation.Horizontal); slider.setRange(low, high)
            value_label = QLabel("0"); value_label.setFixedWidth(50)
            slider.valueChanged.connect(lambda value, n=name, s=scale: self._slider_changed(n, value / s))
            layout.addWidget(slider, 1); layout.addWidget(value_label)
            self.sliders[name] = (slider, value_label, scale)
            form.addRow(label, row)
        panel_layout.addLayout(form)
        preset_row = QHBoxLayout()
        self.preset_combo = QComboBox(); self.preset_combo.addItems(preset_names())
        apply_preset = QPushButton("Apply preset"); apply_preset.clicked.connect(self.apply_preset)
        preset_row.addWidget(self.preset_combo, 1); preset_row.addWidget(apply_preset)
        panel_layout.addLayout(preset_row)
        buttons = QHBoxLayout()
        for label, handler in (("Reset", self.reset_settings), ("Copy", self.copy_settings),
                               ("Paste", self.paste_settings), ("Sync selected", self.sync_settings)):
            button = QPushButton(label); button.clicked.connect(handler); buttons.addWidget(button)
        panel_layout.addLayout(buttons)
        undo_row = QHBoxLayout()
        undo = QPushButton("Undo"); undo.clicked.connect(self.undo)
        redo = QPushButton("Redo"); redo.clicked.connect(self.redo)
        undo_row.addWidget(undo); undo_row.addWidget(redo); panel_layout.addLayout(undo_row)
        panel_layout.addStretch()
        panel_scroll.setWidget(panel)
        splitter.addWidget(panel_scroll)
        splitter.setSizes([440, 760, 340])
        self.setCentralWidget(splitter)

        status = QStatusBar(); self.setStatusBar(status)
        self.status_label = QLabel("Local-only • originals are never modified")
        self.progress = QProgressBar(); self.progress.setVisible(False); self.progress.setMaximumWidth(300)
        self.cancel_button = QPushButton("Cancel"); self.cancel_button.setVisible(False); self.cancel_button.clicked.connect(self.cancel_jobs)
        status.addWidget(self.status_label, 1); status.addPermanentWidget(self.progress); status.addPermanentWidget(self.cancel_button)

    def _build_shortcuts(self) -> None:
        for number in range(6):
            QShortcut(QKeySequence(str(number)), self, activated=lambda n=number: self.set_rating(n))
        QShortcut(QKeySequence("P"), self, activated=lambda: self.set_cull(CullStatus.KEEP))
        QShortcut(QKeySequence("U"), self, activated=lambda: self.set_cull(CullStatus.REVIEW))
        QShortcut(QKeySequence("X"), self, activated=lambda: self.set_cull(CullStatus.REJECT))
        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, activated=self.redo)

    def _action(self, toolbar, label, handler, shortcut=None):
        action = QAction(label, self); action.triggered.connect(handler)
        if shortcut: action.setShortcut(QKeySequence(shortcut))
        toolbar.addAction(action); return action

    def create_project(self) -> None:
        name, _ = QFileDialog.getSaveFileName(self, "Create FramePilot project", "", "FramePilot Project (*.fp-project)")
        if name:
            if not name.lower().endswith(".fp-project"): name += ".fp-project"
            self._set_database(Path(name))
            self.status_label.setText(f"Created project: {Path(name).name}")

    def open_project(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Open FramePilot project", "", "FramePilot Project (*.fp-project)")
        if name:
            self._set_database(Path(name)); self.photos = self.database.load_photos()  # type: ignore[union-attr]
            self._populate_browser(); self.status_label.setText(f"Opened {len(self.photos)} photos")

    def _set_database(self, path: Path) -> None:
        if self.database: self.database.close()
        self.database = ProjectDatabase(path); self.project_path = path

    def open_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open RAW photo folder")
        if not folder: return
        if not self.database:
            app_root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FramePilot" / "projects"
            app_root.mkdir(parents=True, exist_ok=True)
            safe = Path(folder).name.replace(" ", "-") or "untitled"
            self._set_database(app_root / f"{safe}.fp-project")
        worker = FunctionWorker(lambda w: discover_raw_files(folder, lambda: w.cancelled))
        worker.signals.result.connect(self._import_discovered)
        self._start_worker(worker, "Discovering RAW files…")

    def _import_discovered(self, photos: list[PhotoRecord]) -> None:
        existing = {str(p.path): p for p in self.database.load_photos()} if self.database else {}
        for p in photos:
            old = existing.get(str(p.path))
            if old: p = old
            else: self.database.upsert_photo(p)  # type: ignore[union-attr]
            existing[str(p.path)] = p
        self.photos = sorted(existing.values(), key=lambda p: (p.capture_time or "", p.filename.casefold()))
        self._populate_browser()
        self.status_label.setText(f"Imported {len(photos)} RAW files • {len(self.photos)} in project")
        self._load_thumbnails()

    def _populate_browser(self) -> None:
        self.browser.clear()
        for index, photo in enumerate(self.photos):
            item = QListWidgetItem(self._item_text(photo)); item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(str(photo.path)); self.browser.addItem(item)
        self._apply_filter()
        if self.photos: self.browser.setCurrentRow(0)

    def _apply_filter(self, *_args) -> None:
        if not hasattr(self, "browser"): return
        mode = self.filter_combo.currentText() if hasattr(self, "filter_combo") else "All"
        for row in range(self.browser.count()):
            item = self.browser.item(row); index = item.data(Qt.ItemDataRole.UserRole)
            photo = self.photos[index]
            visible = (mode == "All" or mode.lower() == photo.cull_status.value
                       or (mode == "Rated" and photo.rating > 0))
            item.setHidden(not visible)

    def _sort_changed(self, mode: str) -> None:
        keys = {
            "Filename": lambda p: p.filename.casefold(),
            "Capture time": lambda p: (p.capture_time or "", p.filename.casefold()),
            "Rating": lambda p: (-p.rating, p.filename.casefold()),
            "Quality": lambda p: (-p.analysis.quality_score, p.filename.casefold()),
        }
        self.photos.sort(key=keys.get(mode, keys["Filename"]))
        self._populate_browser()

    def _item_text(self, p: PhotoRecord) -> str:
        stars = "★" * p.rating
        return f"{p.filename}\n{p.cull_status.value.upper()} {stars}\n{p.camera or ''}"

    def _load_thumbnails(self) -> None:
        def task(worker):
            total = len(self.photos)
            for i, photo in enumerate(self.photos):
                if worker.cancelled: break
                try: worker.signals.item.emit((i, self.decoder.thumbnail(photo)))
                except Exception as exc: worker.signals.item.emit((i, exc))
                worker.signals.progress.emit(i + 1, total, photo.filename)
        worker = FunctionWorker(task); worker.signals.item.connect(self._thumbnail_ready)
        self._start_worker(worker, "Building thumbnails…")

    def _thumbnail_ready(self, payload) -> None:
        index, value = payload
        if index >= self.browser.count(): return
        if isinstance(value, Exception):
            self.browser.item(index).setToolTip(str(value)); return
        self.browser.item(index).setIcon(pil_to_pixmap(value))

    def _photo_selected(self, item, previous=None) -> None:
        if item is None: return
        index = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(index, int) or index >= len(self.photos): return
        self.current_photo = self.photos[index]
        self._show_settings(self.current_photo.settings)
        p = self.current_photo
        self.photo_info.setText(f"{p.filename}\n{p.camera or 'Camera metadata unavailable'}\n"
                                f"{p.cull_status.value.upper()} • {p.rating} stars\n{p.analysis.explanation}")
        worker = FunctionWorker(lambda w: self.decoder.preview(p))
        worker.signals.result.connect(lambda image, expected=p: self._preview_ready(expected, image))
        self._start_worker(worker, f"Loading {p.filename}…", show_progress=False)

    def _preview_ready(self, expected: PhotoRecord, image) -> None:
        if expected is not self.current_photo: return
        self.original_preview = image; self.refresh_preview()

    def refresh_preview(self) -> None:
        if self.original_preview is None or self.current_photo is None: return
        image = self.original_preview if self.before_after.isChecked() else render_preview(self.original_preview, self.current_photo.settings)
        pixmap = pil_to_pixmap(image)
        if self.zoom_combo.currentText() == "100%":
            self.preview_scroll.setWidgetResizable(False); self.preview.setMinimumSize(0, 0)
            self.preview.setPixmap(pixmap); self.preview.resize(pixmap.size())
        else:
            self.preview_scroll.setWidgetResizable(True); self.preview.setMinimumSize(560, 420)
            viewport = self.preview_scroll.viewport().size()
            self.preview.setPixmap(pixmap.scaled(viewport, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.original_preview is not None: self.refresh_preview()

    def _show_settings(self, settings: DevelopSettings) -> None:
        self._updating_controls = True
        self.wb.setCurrentText(settings.white_balance)
        for name, (slider, label, scale) in self.sliders.items():
            value = getattr(settings, name); slider.setValue(round(value * scale)); label.setText(f"{value:g}")
        self._updating_controls = False

    def _slider_changed(self, name: str, value: float) -> None:
        slider, label, _ = self.sliders[name]; label.setText(f"{value:g}")
        if self._updating_controls or not self.current_photo: return
        self._commit_settings(self.current_photo.settings.with_value(name, value))

    def _wb_changed(self, value: str) -> None:
        if not self._updating_controls and self.current_photo:
            self._commit_settings(self.current_photo.settings.with_value("white_balance", value))

    def _commit_settings(self, settings: DevelopSettings, record_history: bool = True) -> None:
        p = self.current_photo
        if not p: return
        if record_history and p.id is not None:
            history = self.history.setdefault(p.id, [replace(p.settings)])
            pos = self.history_position.get(p.id, len(history) - 1)
            del history[pos + 1:]; history.append(replace(settings)); self.history_position[p.id] = len(history) - 1
        p.settings = settings; self.database.save_photo(p) if self.database else None
        self.refresh_preview()

    def reset_settings(self):
        if self.current_photo: self._commit_settings(DevelopSettings()); self._show_settings(self.current_photo.settings)
    def copy_settings(self):
        if self.current_photo: self.clipboard_settings = replace(self.current_photo.settings); self.status_label.setText("Develop settings copied")
    def paste_settings(self):
        if self.current_photo and self.clipboard_settings: self._commit_settings(replace(self.clipboard_settings)); self._show_settings(self.current_photo.settings)
    def sync_settings(self):
        if not self.current_photo: return
        selected = self.selected_photos()
        for p in selected: p.settings = replace(self.current_photo.settings)
        if self.database: self.database.save_many(selected)
        self.status_label.setText(f"Synchronised settings to {len(selected)} photos")
    def apply_preset(self):
        if self.current_photo: self._commit_settings(get_preset(self.preset_combo.currentText())); self._show_settings(self.current_photo.settings)
    def undo(self): self._move_history(-1)
    def redo(self): self._move_history(1)
    def _move_history(self, delta: int):
        p = self.current_photo
        if not p or p.id is None: return
        history = self.history.get(p.id); pos = self.history_position.get(p.id, -1)
        if not history or not 0 <= pos + delta < len(history): return
        pos += delta; self.history_position[p.id] = pos; self._commit_settings(replace(history[pos]), False); self._show_settings(p.settings)

    def selected_photos(self) -> list[PhotoRecord]:
        result = []
        for item in self.browser.selectedItems():
            index = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(index, int) and index < len(self.photos): result.append(self.photos[index])
        return result or ([self.current_photo] if self.current_photo else [])

    def set_rating(self, rating: int):
        for p in self.selected_photos(): p.rating = rating
        self._save_selection_refresh()
    def set_cull(self, status: CullStatus):
        for p in self.selected_photos(): p.cull_status = status; p.cull_override = True
        self._save_selection_refresh()
    def _save_selection_refresh(self):
        selected = self.selected_photos()
        if self.database: self.database.save_many(selected)
        for item in self.browser.selectedItems():
            index = item.data(Qt.ItemDataRole.UserRole); item.setText(self._item_text(self.photos[index]))

    def analyse_photos(self) -> None:
        targets = self.selected_photos() if self.browser.selectedItems() else self.photos
        def task(worker):
            for i, photo in enumerate(targets):
                if worker.cancelled: break
                try:
                    photo.analysis = analyse_image(self.decoder.thumbnail(photo, 1024))
                    if not photo.cull_override: photo.cull_status = suggested_status(photo.analysis)
                except Exception as exc:
                    photo.analysis.preview_failed = True; photo.analysis.explanation = f"Preview failed: {exc}"
                    if not photo.cull_override: photo.cull_status = CullStatus.REVIEW
                worker.signals.progress.emit(i + 1, len(targets), photo.filename)
            group_similar(targets)
            return targets
        worker = FunctionWorker(task); worker.signals.result.connect(self._analysis_ready)
        self._start_worker(worker, f"Analysing {len(targets)} photos…")

    def _analysis_ready(self, targets):
        if self.database: self.database.save_many(targets)
        self._populate_browser(); self.status_label.setText(f"Analysed {len(targets)} photos locally")

    def export_xmp_selected(self) -> None:
        targets = self.selected_photos()
        if not targets: return
        existing = [p for p in targets if p.path.with_suffix(".xmp").exists()]
        overwrite = False
        if existing:
            choice = QMessageBox.warning(self, "Existing sidecars", f"{len(existing)} XMP sidecars exist. Back up and overwrite them?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if choice != QMessageBox.StandardButton.Yes: return
            overwrite = True
        def task(worker):
            results = []
            for i, p in enumerate(targets):
                if worker.cancelled: break
                result = export_sidecar(p.path, p.settings, overwrite=overwrite, backup=True)
                p.export_status = "xmp-exported" if result.success else "xmp-failed"
                results.append(result); worker.signals.progress.emit(i + 1, len(targets), p.filename)
            return results
        worker = FunctionWorker(task); worker.signals.result.connect(self._xmp_ready)
        self._start_worker(worker, f"Exporting {len(targets)} XMP sidecars…")

    def _xmp_ready(self, results):
        ok = sum(r.success for r in results); failed = [r for r in results if not r.success]
        if self.database: self.database.save_many(self.selected_photos())
        message = f"Exported {ok} of {len(results)} XMP sidecars."
        if failed: message += "\n\n" + "\n".join(f"{r.source.name}: {r.message}" for r in failed[:8])
        QMessageBox.information(self, "XMP export", message)

    def export_jpeg_selected(self):
        targets = self.selected_photos()
        if not targets: return
        folder = QFileDialog.getExistingDirectory(self, "Choose JPEG export folder")
        if not folder: return
        def task(worker):
            errors = []
            for i, p in enumerate(targets):
                if worker.cancelled: break
                try: export_jpeg(self.decoder.preview(p, 10000), p.settings, Path(folder) / f"{p.path.stem}.jpg")
                except Exception as exc: errors.append(f"{p.filename}: {exc}")
                worker.signals.progress.emit(i + 1, len(targets), p.filename)
            return errors
        worker = FunctionWorker(task); worker.signals.result.connect(lambda errors: QMessageBox.information(self, "JPEG export", f"Completed with {len(errors)} errors" + (("\n" + "\n".join(errors[:8])) if errors else "")))
        self._start_worker(worker, f"Rendering {len(targets)} JPEGs…")

    def save_project(self):
        if self.database: self.database.save_many(self.photos); self.status_label.setText("Project saved")
        else: self.create_project()

    def clear_cache(self):
        if self.active_workers:
            QMessageBox.information(self, "Cache busy", "Wait for current background work before clearing the cache.")
            return
        choice = QMessageBox.question(self, "Clear thumbnail cache",
            "Remove cached previews? Originals and project edits are unaffected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if choice == QMessageBox.StandardButton.Yes:
            count, size = self.decoder.clear_cache()
            self.status_label.setText(f"Removed {count} cached files ({size / (1024 * 1024):.1f} MB)")

    def cancel_jobs(self):
        for worker in self.active_workers: worker.cancel()
        self.status_label.setText("Cancelling after current file…")

    def _start_worker(self, worker: FunctionWorker, message: str, show_progress: bool = True):
        self.active_workers.append(worker); self.status_label.setText(message)
        self.progress.setVisible(show_progress); self.cancel_button.setVisible(show_progress)
        worker.signals.progress.connect(self._progress_changed)
        worker.signals.error.connect(lambda trace: (log.error(trace), QMessageBox.critical(self, "FramePilot error", trace.splitlines()[-1])))
        worker.signals.finished.connect(lambda w=worker: self._worker_finished(w))
        self.thread_pool.start(worker)

    def _progress_changed(self, done: int, total: int, name: str):
        self.progress.setRange(0, max(1, total)); self.progress.setValue(done); self.progress.setFormat(f"{done}/{total}")
        self.status_label.setText(name)

    def _worker_finished(self, worker):
        if worker in self.active_workers: self.active_workers.remove(worker)
        if not self.active_workers:
            self.progress.setVisible(False); self.cancel_button.setVisible(False)

    def closeEvent(self, event):
        self.cancel_jobs()
        if self.database: self.database.save_many(self.photos); self.database.close()
        event.accept()

    @staticmethod
    def _stylesheet() -> str:
        return """
        QMainWindow, QWidget { background:#202124; color:#dedede; font-family:'Segoe UI'; font-size:10pt; }
        QToolBar { background:#292a2d; border-bottom:1px solid #3b3b3b; spacing:5px; padding:5px; }
        QToolButton, QPushButton { background:#34363a; border:1px solid #494b50; border-radius:3px; padding:6px 10px; }
        QToolButton:hover, QPushButton:hover { background:#41444a; }
        QListWidget { background:#17181a; border:0; outline:0; }
        QListWidget::item { color:#cfd1d4; padding:5px; border:1px solid transparent; }
        QListWidget::item:selected { background:#343a40; border:1px solid #d5a642; }
        QComboBox { background:#303237; border:1px solid #4b4d52; padding:5px; }
        QSlider::groove:horizontal { height:3px; background:#555; }
        QSlider::handle:horizontal { background:#d5a642; width:12px; margin:-5px 0; border-radius:6px; }
        QStatusBar { background:#17181a; border-top:1px solid #353535; }
        QProgressBar { border:1px solid #454545; text-align:center; background:#222; }
        QProgressBar::chunk { background:#b58a30; }
        """
