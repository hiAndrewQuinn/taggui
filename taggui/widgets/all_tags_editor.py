from enum import Enum
from functools import reduce
from operator import or_
from typing import Literal

from PySide6.QtCore import (QItemSelection, QItemSelectionModel, Qt, Signal,
                            Slot)
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (QAbstractItemView, QDockWidget, QHBoxLayout,
                               QLabel, QLineEdit, QListView, QMessageBox,
                               QVBoxLayout, QWidget)
from pyparsing import (CaselessLiteral, Group, ParseException, Suppress, Word,
                       nums, one_of)

from taggui.models.proxy_tag_counter_model import ProxyTagCounterModel
from taggui.models.tag_counter_model import TagCounterModel
from taggui.utils.big_widgets import TallPushButton
from taggui.utils.enums import AllTagsSortBy, SortOrder
from taggui.utils.filter_parser import (build_boolean_parser, format_ast,
                                        optionally_quoted_string,
                                        replace_filter_wildcards)
from taggui.utils.settings_widgets import SettingsComboBox
from taggui.utils.text_edit_item_delegate import TextEditItemDelegate
from taggui.utils.utils import get_confirmation_dialog_reply, list_with_and, pluralize


ParseStatus = Literal['empty', 'ok', 'invalid']


class FilterLineEdit(QLineEdit):
    def __init__(self):
        super().__init__()
        self.setPlaceholderText('Filter Tags')
        self.setStyleSheet('padding: 8px;')
        self.setClearButtonEnabled(True)
        self.last_parse_status: ParseStatus = 'empty'
        oqs = optionally_quoted_string()
        string_filter_keys = ['name', 'co']
        string_filter_expressions = [Group(CaselessLiteral(key) + Suppress(':')
                                           + oqs)
                                     for key in string_filter_keys]
        comparison_operator = one_of('= == != < > <= >=')
        number_filter_keys = ['count', 'length']
        number_filter_expressions = [Group(CaselessLiteral(key) + Suppress(':')
                                           + comparison_operator + Word(nums))
                                     for key in number_filter_keys]
        string_filter_expressions = reduce(or_, string_filter_expressions)
        number_filter_expressions = reduce(or_, number_filter_expressions)
        filter_expressions = (string_filter_expressions
                              | number_filter_expressions
                              | oqs)
        self.filter_text_parser = build_boolean_parser(filter_expressions)

    def parse_filter_text(self) -> list | str | None:
        filter_text = self.text()
        if not filter_text:
            self.last_parse_status = 'empty'
            self.setStyleSheet('padding: 8px;')
            return None
        try:
            filter_ = self.filter_text_parser.parse_string(
                filter_text, parse_all=True).as_list()[0]
            filter_ = replace_filter_wildcards(filter_)
            self.last_parse_status = 'ok'
            self.setStyleSheet('padding: 8px;')
            return filter_
        except ParseException:
            self.last_parse_status = 'invalid'
            if self.palette().color(self.backgroundRole()).lightness() < 128:
                self.setStyleSheet('padding: 8px; background-color: #442222;')
            else:
                self.setStyleSheet('padding: 8px; background-color: #ffdddd;')
            return None


class ClickAction(str, Enum):
    FILTER_IMAGES = 'Filter images for tag'
    ADD_TO_SELECTED = 'Add tag to selected images'


class AllTagsList(QListView):
    image_list_filter_requested = Signal(str)
    tag_addition_requested = Signal(str)
    tags_deletion_requested = Signal(list)

    def __init__(self, proxy_tag_counter_model: ProxyTagCounterModel,
                 all_tags_editor: 'AllTagsEditor'):
        super().__init__()
        self.setModel(proxy_tag_counter_model)
        self.all_tags_editor = all_tags_editor
        self.setItemDelegate(TextEditItemDelegate(self))
        self.setWordWrap(True)
        # `selectionChanged` must be used and not `currentChanged` because
        # `currentChanged` is not emitted when the same tag is deselected and
        # selected again.
        self.selectionModel().selectionChanged.connect(
            self.handle_selection_change)

    def mousePressEvent(self, event: QMouseEvent):
        click_action = (self.all_tags_editor.click_action_combo_box
                        .currentText())
        if click_action == ClickAction.ADD_TO_SELECTED:
            index = self.indexAt(event.pos())
            tag = index.data(Qt.ItemDataRole.EditRole)
            self.tag_addition_requested.emit(tag)
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        """
        Delete all instances of the selected tag when the delete key or
        backspace key is pressed.
        """
        if event.key() not in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            super().keyPressEvent(event)
            return
        selected_indices = self.selectedIndexes()
        if not selected_indices:
            return
        tags = []
        tags_count = 0
        for selected_index in selected_indices:
            tag, tag_count = selected_index.data(Qt.ItemDataRole.UserRole)
            tags.append(tag)
            tags_count += tag_count
        question = (f'Delete {tags_count} {pluralize("instance", tags_count)} '
                    f'of ')
        if len(tags) < 10:
            quoted_tags = [f'"{tag}"' for tag in tags]
            question += (f'{pluralize("tag", len(tags))} '
                         f'{list_with_and(quoted_tags)}?')
        else:
            question += f'{len(tags)} tags?'
        reply = get_confirmation_dialog_reply(
            title=f'Delete {pluralize("Tag", len(tags))}', question=question)
        if reply == QMessageBox.StandardButton.Yes:
            self.tags_deletion_requested.emit(tags)

    def handle_selection_change(self, selected: QItemSelection, _):
        click_action = (self.all_tags_editor.click_action_combo_box
                        .currentText())
        if click_action != ClickAction.FILTER_IMAGES:
            return
        if not selected.indexes():
            return
        selected_tag = selected.indexes()[0].data(Qt.ItemDataRole.EditRole)
        self.image_list_filter_requested.emit(selected_tag)


class AllTagsEditor(QDockWidget):
    def __init__(self, tag_counter_model: TagCounterModel):
        super().__init__()
        self.tag_counter_model = tag_counter_model

        # Each `QDockWidget` needs a unique object name for saving its state.
        self.setObjectName('all_tags_editor')
        self.setWindowTitle('All Tags')
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea
                             | Qt.DockWidgetArea.RightDockWidgetArea)
        self.proxy_tag_counter_model = ProxyTagCounterModel(
            self.tag_counter_model)
        self.proxy_tag_counter_model.setFilterRole(Qt.ItemDataRole.EditRole)
        self.filter_line_edit = FilterLineEdit()
        click_action_layout = QHBoxLayout()
        click_action_label = QLabel('Tag click action')
        self.click_action_combo_box = SettingsComboBox(
            key='all_tags_click_action')
        self.click_action_combo_box.addItems(list(ClickAction))
        click_action_layout.addWidget(click_action_label)
        click_action_layout.addWidget(self.click_action_combo_box, stretch=1)
        sort_layout = QHBoxLayout()
        sort_label = QLabel('Sort by')
        self.sort_by_combo_box = SettingsComboBox(key='all_tags_sort_by',
                                                  default='Frequency')
        self.sort_by_combo_box.addItems(list(AllTagsSortBy))
        self.sort_by_combo_box.currentTextChanged.connect(self.sort_tags)
        self.sort_order_combo_box = SettingsComboBox(key='all_tags_sort_order',
                                                     default='Descending')
        self.sort_order_combo_box.addItems(list(SortOrder))
        self.sort_order_combo_box.currentTextChanged.connect(self.sort_tags)
        sort_layout.addWidget(sort_label)
        sort_layout.addWidget(self.sort_by_combo_box, stretch=1)
        sort_layout.addWidget(self.sort_order_combo_box, stretch=1)
        self.clear_filter_button = TallPushButton('Clear Image List Filter')
        self.clear_filter_button.setFixedHeight(
            int(self.clear_filter_button.sizeHint().height() * 1.5))
        self.all_tags_list = AllTagsList(self.proxy_tag_counter_model,
                                         all_tags_editor=self)
        self.tag_count_label = QLabel()
        # A container widget is required to use a layout with a `QDockWidget`.
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(self.filter_line_edit)
        layout.addLayout(click_action_layout)
        layout.addLayout(sort_layout)
        layout.addWidget(self.clear_filter_button)
        layout.addWidget(self.all_tags_list)
        layout.addWidget(self.tag_count_label)
        self.setWidget(container)

        self.proxy_tag_counter_model.modelReset.connect(
            self.update_tag_count_label)
        self.proxy_tag_counter_model.rowsInserted.connect(
            self.update_tag_count_label)
        self.proxy_tag_counter_model.rowsRemoved.connect(
            self.update_tag_count_label)
        self.filter_line_edit.textChanged.connect(self.set_filter)
        self.filter_line_edit.textChanged.connect(self.update_tag_count_label)
        self.click_action_combo_box.currentTextChanged.connect(
            self.set_selection_mode)
        self.set_selection_mode(self.click_action_combo_box.currentText())
        self.sort_tags()

    @Slot()
    def sort_tags(self):
        self.proxy_tag_counter_model.sort_by = (self.sort_by_combo_box
                                                .currentText())
        if self.sort_order_combo_box.currentText() == SortOrder.ASCENDING:
            sort_order = Qt.SortOrder.AscendingOrder
        else:
            sort_order = Qt.SortOrder.DescendingOrder
        # `invalidate()` must be called to force the proxy model to re-sort.
        self.proxy_tag_counter_model.invalidate()
        self.proxy_tag_counter_model.sort(0, sort_order)

    @Slot()
    def set_filter(self):
        parsed = self.filter_line_edit.parse_filter_text()
        self.proxy_tag_counter_model.filter = parsed
        # `invalidate()` must be called to force the proxy model to re-filter.
        self.proxy_tag_counter_model.invalidate()
        status = self.filter_line_edit.last_parse_status
        if status == 'empty':
            self.filter_line_edit.setToolTip('')
        elif status == 'invalid':
            self.filter_line_edit.setToolTip('Invalid filter expression')
        else:
            self.filter_line_edit.setToolTip(format_ast(parsed))

    @Slot()
    def update_tag_count_label(self):
        total_tag_count = self.tag_counter_model.rowCount()
        filtered_tag_count = self.proxy_tag_counter_model.rowCount()
        self.tag_count_label.setText(f'{filtered_tag_count} / '
                                     f'{total_tag_count} Tags')

    @Slot(str)
    def set_selection_mode(self, click_action: str):
        if click_action == ClickAction.FILTER_IMAGES:
            self.all_tags_list.setSelectionMode(
                QAbstractItemView.SelectionMode.ExtendedSelection)
        elif click_action == ClickAction.ADD_TO_SELECTED:
            self.all_tags_list.setSelectionMode(
                QAbstractItemView.SelectionMode.SingleSelection)
            self.all_tags_list.selectionModel().select(
                self.all_tags_list.selectionModel().currentIndex(),
                QItemSelectionModel.SelectionFlag.ClearAndSelect)
