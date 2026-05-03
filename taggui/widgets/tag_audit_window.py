"""Standalone three-pane "Tag Audit" window for reverse search / bulk edits.

Layout:
    [ master tag list ] | [ image grid ] | [ reverse tag inspector ]

The window shares the main window's ``ImageListModel`` and
``TagCounterModel`` source models but owns its own proxy instances so
filter/sort state is independent. Bulk edits are dispatched through the
shared ``BulkTagController`` and propagate back to the main window via the
existing ``dataChanged`` signal, which already drives a tag-counter rebuild.
"""
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QInputDialog,
                               QLabel, QListView, QMainWindow, QPushButton,
                               QRadioButton, QSplitter, QStyledItemDelegate,
                               QVBoxLayout, QWidget)
from transformers import PreTrainedTokenizerBase

from taggui.models.bulk_tag_controller import BulkTagController
from taggui.models.image_list_model import ImageListModel
from taggui.models.proxy_image_list_model import ProxyImageListModel
from taggui.models.proxy_selection_tags_model import ProxySelectionTagsModel
from taggui.models.proxy_tag_counter_model import ProxyTagCounterModel
from taggui.models.selection_tags_model import SelectionTagsModel
from taggui.models.tag_counter_model import TagCounterModel
from taggui.utils.enums import AllTagsSortBy, SortOrder
from taggui.utils.filter_parser import format_ast
from taggui.utils.settings import get_settings
from taggui.widgets.all_tags_editor import FilterLineEdit as TagFilterLineEdit
from taggui.widgets.image_list import ImageListView


class _IntersectionFontDelegate(QStyledItemDelegate):
    """Renders intersection tags in bold; union-only tags in normal weight."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        is_intersection = index.data(SelectionTagsModel.IS_INTERSECTION_ROLE)
        if is_intersection:
            font = QFont(option.font)
            font.setBold(True)
            option.font = font


class TagAuditWindow(QMainWindow):
    SETTINGS_KEY_GEOMETRY = 'tag_audit_window/geometry'
    SETTINGS_KEY_SPLITTER = 'tag_audit_window/splitter_state'

    def __init__(self, image_list_model: ImageListModel,
                 tag_counter_model: TagCounterModel,
                 bulk_controller: BulkTagController,
                 tokenizer: PreTrainedTokenizerBase,
                 tag_separator: str,
                 image_width: int,
                 parent=None):
        super().__init__(parent)
        self.setObjectName('tag_audit_window')
        self.setWindowTitle('Tag Audit')
        self.image_list_model = image_list_model
        self.bulk_controller = bulk_controller
        self.tag_separator = tag_separator
        self.settings = get_settings()

        self.master_tags_proxy = ProxyTagCounterModel(tag_counter_model)
        self.master_tags_proxy.setFilterRole(Qt.ItemDataRole.EditRole)
        self.images_proxy = ProxyImageListModel(
            image_list_model, tokenizer, tag_separator)
        self.selection_tags_model = SelectionTagsModel(image_list_model)
        self.inspector_proxy = ProxySelectionTagsModel(
            self.selection_tags_model)
        self.inspector_proxy.sort_by = AllTagsSortBy.FREQUENCY

        self.master_tags_view: QListView | None = None
        self.images_view: ImageListView | None = None
        self.inspector_view: QListView | None = None
        self.inspector_count_label: QLabel | None = None
        self.master_tags_count_label: QLabel | None = None
        self.images_count_label: QLabel | None = None
        self.intersection_only_radio: QRadioButton | None = None
        self.union_radio: QRadioButton | None = None
        self.add_tag_button: QPushButton | None = None
        self.delete_tags_button: QPushButton | None = None
        self.merge_tags_button: QPushButton | None = None
        self.master_intersection_radio: QRadioButton | None = None
        self.master_union_radio: QRadioButton | None = None
        self.clear_master_selection_button: QPushButton | None = None

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(self._build_master_tags_pane())
        self.splitter.addWidget(self._build_images_pane(image_width))
        self.splitter.addWidget(self._build_inspector_pane())
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setStretchFactor(2, 2)
        self.setCentralWidget(self.splitter)

        self._connect_signals()
        self._restore_state()
        # Ensure initial proxy sort/filter are applied.
        self.master_tags_proxy.sort_by = AllTagsSortBy.FREQUENCY
        self.master_tags_proxy.invalidate()
        self.master_tags_proxy.sort(0, Qt.SortOrder.DescendingOrder)
        self._update_master_tags_count()
        self._update_images_count()
        self._update_inspector_count()
        self._update_action_buttons_enabled()

    # ---- pane builders ----------------------------------------------------

    def _build_master_tags_pane(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel('Master Tag List'))
        self.master_filter = TagFilterLineEdit()
        layout.addWidget(self.master_filter)

        combiner_row = QHBoxLayout()
        self.master_intersection_radio = QRadioButton('Intersection (AND)')
        self.master_intersection_radio.setChecked(True)
        self.master_union_radio = QRadioButton('Union (OR)')
        combiner_row.addWidget(self.master_intersection_radio)
        combiner_row.addWidget(self.master_union_radio)
        combiner_row.addStretch(1)
        self.clear_master_selection_button = QPushButton('Clear selection')
        combiner_row.addWidget(self.clear_master_selection_button)
        layout.addLayout(combiner_row)

        self.master_tags_view = QListView()
        self.master_tags_view.setModel(self.master_tags_proxy)
        self.master_tags_view.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.master_tags_view.setUniformItemSizes(True)
        layout.addWidget(self.master_tags_view, stretch=1)
        self.master_tags_count_label = QLabel()
        self.master_tags_count_label.setStyleSheet('color: gray;')
        layout.addWidget(self.master_tags_count_label)
        return container

    def _build_images_pane(self, image_width: int) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        header = QHBoxLayout()
        header.addWidget(QLabel('Images matching selected tags'))
        header.addStretch(1)
        self.images_count_label = QLabel()
        self.images_count_label.setStyleSheet('color: gray;')
        header.addWidget(self.images_count_label)
        layout.addLayout(header)
        self.images_view = ImageListView(
            container, self.images_proxy, self.tag_separator, image_width)
        self.images_view.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        layout.addWidget(self.images_view, stretch=1)
        return container

    def _build_inspector_pane(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel('Reverse Inspector'))
        self.inspector_filter = TagFilterLineEdit()
        layout.addWidget(self.inspector_filter)

        toggle_row = QHBoxLayout()
        self.intersection_only_radio = QRadioButton('Intersection only')
        self.union_radio = QRadioButton('All (union)')
        self.union_radio.setChecked(True)
        toggle_row.addWidget(self.intersection_only_radio)
        toggle_row.addWidget(self.union_radio)
        toggle_row.addStretch(1)
        layout.addLayout(toggle_row)

        self.inspector_view = QListView()
        self.inspector_view.setModel(self.inspector_proxy)
        self.inspector_view.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.inspector_view.setItemDelegate(
            _IntersectionFontDelegate(self.inspector_view))
        self.inspector_view.setUniformItemSizes(True)
        layout.addWidget(self.inspector_view, stretch=1)

        self.inspector_count_label = QLabel(
            'Select images to inspect their tags')
        self.inspector_count_label.setStyleSheet('color: gray;')
        layout.addWidget(self.inspector_count_label)

        action_row = QHBoxLayout()
        self.add_tag_button = QPushButton('Add tag…')
        self.delete_tags_button = QPushButton('Delete from selection')
        self.merge_tags_button = QPushButton('Merge into…')
        action_row.addWidget(self.add_tag_button)
        action_row.addWidget(self.delete_tags_button)
        action_row.addWidget(self.merge_tags_button)
        layout.addLayout(action_row)

        return container

    # ---- signal wiring ----------------------------------------------------

    def _connect_signals(self):
        self.master_filter.textChanged.connect(self._apply_master_filter)
        self.inspector_filter.textChanged.connect(self._apply_inspector_filter)

        self.master_tags_view.selectionModel().selectionChanged.connect(
            self._on_master_tags_changed)
        self.images_view.selectionModel().selectionChanged.connect(
            self._on_image_selection_changed)
        self.inspector_view.selectionModel().selectionChanged.connect(
            self._update_action_buttons_enabled)

        self.intersection_only_radio.toggled.connect(
            self._on_intersection_only_toggled)
        self.master_intersection_radio.toggled.connect(
            self._on_master_combiner_toggled)
        self.clear_master_selection_button.clicked.connect(
            self._on_clear_master_selection)
        self.master_tags_proxy.sourceModel().modelReset.connect(
            self._prune_sticky_tags)

        self.images_proxy.rowsInserted.connect(self._update_images_count)
        self.images_proxy.rowsRemoved.connect(self._update_images_count)
        self.images_proxy.modelReset.connect(self._update_images_count)
        self.master_tags_proxy.rowsInserted.connect(
            self._update_master_tags_count)
        self.master_tags_proxy.rowsRemoved.connect(
            self._update_master_tags_count)
        self.master_tags_proxy.modelReset.connect(
            self._update_master_tags_count)
        self.selection_tags_model.modelReset.connect(
            self._update_inspector_count)

        # Refresh the inspector when the dataset mutates (from anywhere).
        self.image_list_model.dataChanged.connect(self._refresh_after_mutation)

        self.add_tag_button.clicked.connect(self._on_add_tag_clicked)
        self.delete_tags_button.clicked.connect(
            self._on_delete_tags_clicked)
        self.merge_tags_button.clicked.connect(self._on_merge_tags_clicked)

    # ---- slots ------------------------------------------------------------

    @Slot()
    def _apply_master_filter(self):
        parsed = self.master_filter.parse_filter_text()
        self.master_tags_proxy.filter = parsed
        self.master_tags_proxy.invalidate()
        status = self.master_filter.last_parse_status
        if status == 'empty':
            self.master_filter.setToolTip('')
        elif status == 'invalid':
            self.master_filter.setToolTip('Invalid filter expression')
        else:
            self.master_filter.setToolTip(format_ast(parsed))

    @Slot()
    def _apply_inspector_filter(self):
        parsed = self.inspector_filter.parse_filter_text()
        self.inspector_proxy.filter = parsed
        self.inspector_proxy.invalidate()
        status = self.inspector_filter.last_parse_status
        if status == 'empty':
            self.inspector_filter.setToolTip('')
        elif status == 'invalid':
            self.inspector_filter.setToolTip('Invalid filter expression')
        else:
            self.inspector_filter.setToolTip(format_ast(parsed))

    @Slot()
    def _on_master_tags_changed(self, *_):
        selected = self.master_tags_view.selectedIndexes()
        tags = [idx.data(Qt.ItemDataRole.EditRole) for idx in selected]
        tags = [t for t in tags if t]
        self.master_tags_proxy.sticky_tags = set(tags)
        # Re-sort so newly-sticky tags pin to the bottom under an active
        # filter; harmless when no filter is set.
        self.master_tags_proxy.invalidate()
        combiner = ('AND' if self.master_intersection_radio.isChecked()
                    else 'OR')
        # OR over an empty tag set is the empty set, but `filter=None` means
        # "no filter, accept everything" in ProxyImageListModel. Use the
        # proxy's force_empty flag to express the OR-of-nothing case.
        self.images_proxy.force_empty = (not tags and combiner == 'OR')
        self.images_proxy.filter = self._build_combined_filter(tags, combiner)
        self.images_proxy.invalidateFilter()
        self._update_images_count()
        self._update_master_tags_count()

    @Slot(bool)
    def _on_master_combiner_toggled(self, _checked: bool):
        # `toggled` fires for both radios (one becomes True, one False); the
        # filter rebuild reads the current state directly so we ignore the
        # argument and rebuild once.
        self._on_master_tags_changed()

    @Slot()
    def _on_clear_master_selection(self):
        self.master_tags_view.selectionModel().clearSelection()
        # selectionChanged fires from clearSelection; sticky_tags and the
        # image filter are reset via _on_master_tags_changed.

    @Slot()
    def _prune_sticky_tags(self):
        existing = {tag for tag, _ in
                    self.master_tags_proxy.sourceModel().most_common_tags}
        self.master_tags_proxy.sticky_tags &= existing

    @staticmethod
    def _build_combined_filter(tags: list[str], combiner: str):
        if not tags:
            return None
        atoms = [['tag', tag] for tag in tags]
        if len(atoms) == 1:
            return atoms[0]
        result = []
        for atom in atoms:
            if result:
                result.append(combiner)
            result.append(atom)
        return result

    @Slot()
    def _on_image_selection_changed(self, *_):
        proxy_indices = self.images_view.selectedIndexes()
        source_rows = [self.images_proxy.mapToSource(i).row()
                       for i in proxy_indices]
        self.selection_tags_model.recompute(source_rows)
        self._update_inspector_count()
        self._update_action_buttons_enabled()

    @Slot(bool)
    def _on_intersection_only_toggled(self, checked: bool):
        self.inspector_proxy.intersection_only = checked
        self.inspector_proxy.invalidateFilter()
        self._update_inspector_count()

    @Slot()
    def _refresh_after_mutation(self, *_):
        # Re-run the set math against the current selection so the inspector
        # reflects in-place tag edits made anywhere in the app.
        self._on_image_selection_changed()

    @Slot()
    def _update_master_tags_count(self):
        if self.master_tags_count_label is None:
            return
        total = self.master_tags_proxy.sourceModel().rowCount()
        filtered = self.master_tags_proxy.rowCount()
        self.master_tags_count_label.setText(
            f'{filtered:,} / {total:,} tags')

    @Slot()
    def _update_images_count(self):
        if self.images_count_label is None:
            return
        total = self.images_proxy.sourceModel().rowCount()
        filtered = self.images_proxy.rowCount()
        self.images_count_label.setText(f'{filtered:,} / {total:,} images')

    @Slot()
    def _update_inspector_count(self):
        if self.inspector_count_label is None:
            return
        size = self.selection_tags_model.selection_size
        if size == 0:
            self.inspector_count_label.setText(
                'Select images to inspect their tags')
            return
        n_tags = self.inspector_proxy.rowCount()
        total_tags = self.selection_tags_model.rowCount()
        suffix = ('' if n_tags == total_tags
                  else f' (of {total_tags:,})')
        self.inspector_count_label.setText(
            f'{n_tags:,} tags{suffix} · {size:,} images selected')

    @Slot()
    def _update_action_buttons_enabled(self, *_):
        has_image_selection = self.selection_tags_model.selection_size > 0
        has_tag_selection = bool(
            self.inspector_view.selectionModel().selectedIndexes())
        self.add_tag_button.setEnabled(has_image_selection)
        self.delete_tags_button.setEnabled(
            has_image_selection and has_tag_selection)
        self.merge_tags_button.setEnabled(
            has_image_selection and has_tag_selection)

    # ---- bulk-action handlers --------------------------------------------

    def _selected_image_source_rows(self) -> list[int]:
        return [self.images_proxy.mapToSource(i).row()
                for i in self.images_view.selectedIndexes()]

    def _selected_inspector_tags(self) -> list[str]:
        tags: list[str] = []
        for proxy_idx in self.inspector_view.selectedIndexes():
            source_idx = self.inspector_proxy.mapToSource(proxy_idx)
            tag = self.selection_tags_model.data(
                source_idx, Qt.ItemDataRole.EditRole)
            if tag:
                tags.append(tag)
        return tags

    @Slot()
    def _on_add_tag_clicked(self):
        rows = self._selected_image_source_rows()
        if not rows:
            return
        tag, ok = QInputDialog.getText(
            self, 'Add Tag',
            f'Tag to add to {len(rows)} selected images:')
        if not ok or not tag.strip():
            return
        self.bulk_controller.add_tag(tag.strip(), rows)

    @Slot()
    def _on_delete_tags_clicked(self):
        rows = self._selected_image_source_rows()
        tags = self._selected_inspector_tags()
        if not rows or not tags:
            return
        self.bulk_controller.delete_tags_from_images(tags, rows)

    @Slot()
    def _on_merge_tags_clicked(self):
        rows = self._selected_image_source_rows()
        tags = self._selected_inspector_tags()
        if not rows or not tags:
            return
        target, ok = QInputDialog.getText(
            self, 'Merge Tags',
            f'Merge {len(tags)} selected tag(s) into:')
        if not ok or not target.strip():
            return
        self.bulk_controller.merge_tags(tags, target.strip(), rows)

    # ---- persistence ------------------------------------------------------

    def _restore_state(self):
        if self.settings.contains(self.SETTINGS_KEY_GEOMETRY):
            self.restoreGeometry(
                self.settings.value(self.SETTINGS_KEY_GEOMETRY, type=bytes))
        else:
            self.resize(1200, 700)
        if self.settings.contains(self.SETTINGS_KEY_SPLITTER):
            self.splitter.restoreState(
                self.settings.value(self.SETTINGS_KEY_SPLITTER, type=bytes))

    def closeEvent(self, event: QCloseEvent):
        self.settings.setValue(self.SETTINGS_KEY_GEOMETRY, self.saveGeometry())
        self.settings.setValue(self.SETTINGS_KEY_SPLITTER,
                               self.splitter.saveState())
        super().closeEvent(event)
