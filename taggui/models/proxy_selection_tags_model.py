"""Proxy model for the Reverse Tag Inspector pane.

Mirrors ``ProxyTagCounterModel`` (filter language parity, custom ``lessThan``)
and adds an ``intersection_only`` flag that hides union-only tags when set.
"""
import operator
from fnmatch import fnmatchcase

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel

from taggui.models.selection_tags_model import SelectionTagsModel
from taggui.utils.enums import AllTagsSortBy


_COMPARISON_OPERATORS = {
    '=': operator.eq,
    '==': operator.eq,
    '!=': operator.ne,
    '<': operator.lt,
    '>': operator.gt,
    '<=': operator.le,
    '>=': operator.ge,
}


class ProxySelectionTagsModel(QSortFilterProxyModel):
    def __init__(self, selection_tags_model: SelectionTagsModel):
        super().__init__()
        self.setSourceModel(selection_tags_model)
        self.selection_tags_model = selection_tags_model
        self.sort_by: str | None = None
        self.filter: list | str | None = None
        self.intersection_only: bool = False

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        left_tag, left_count, _ = self.selection_tags_model.entries[left.row()]
        right_tag, right_count, _ = self.selection_tags_model.entries[
            right.row()]
        if self.sort_by == AllTagsSortBy.FREQUENCY:
            return left_count < right_count
        if self.sort_by == AllTagsSortBy.NAME:
            return left_tag < right_tag
        if self.sort_by == AllTagsSortBy.LENGTH:
            return len(left_tag) < len(right_tag)
        return False

    def filterAcceptsRow(self, source_row: int,
                         source_parent: QModelIndex) -> bool:
        tag, count, is_intersection = (self.selection_tags_model
                                       .entries[source_row])
        if self.intersection_only and not is_intersection:
            return False
        if self.filter is None or self.filter == '':
            return True
        return self._matches(tag, count, self.filter)

    def _matches(self, tag: str, count: int, filter_) -> bool:
        if isinstance(filter_, str):
            return fnmatchcase(tag, f'*{filter_}*')
        if len(filter_) == 1:
            return self._matches(tag, count, filter_[0])
        if len(filter_) == 2:
            if filter_[0] == 'NOT':
                return not self._matches(tag, count, filter_[1])
            if filter_[0] == 'name':
                return fnmatchcase(tag, filter_[1])
        if filter_[1] == 'AND':
            return (self._matches(tag, count, filter_[0])
                    and self._matches(tag, count, filter_[2:]))
        if filter_[1] == 'OR':
            return (self._matches(tag, count, filter_[0])
                    or self._matches(tag, count, filter_[2:]))
        comparison_operator = _COMPARISON_OPERATORS[filter_[1]]
        if filter_[0] == 'count':
            return comparison_operator(count, int(filter_[2]))
        if filter_[0] == 'length':
            return comparison_operator(len(tag), int(filter_[2]))
        return False
