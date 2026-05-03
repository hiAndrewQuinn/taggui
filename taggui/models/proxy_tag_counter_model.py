import operator
from fnmatch import fnmatchcase

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt

from taggui.models.tag_counter_model import TagCounterModel
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


class ProxyTagCounterModel(QSortFilterProxyModel):
    def __init__(self, tag_counter_model: TagCounterModel):
        super().__init__()
        self.setSourceModel(tag_counter_model)
        self.tag_counter_model = tag_counter_model
        self.sort_by = None
        self.filter: list | str | None = None
        self._co_cache: dict[str, set[int]] = {}
        # Tags that should remain visible regardless of the active filter
        # (e.g., the user's current selection in the Tag Audit window). Empty
        # by default so consumers that don't opt in see no behavior change.
        self.sticky_tags: set[str] = set()
        # Cache of tag names that match the current filter on their own (i.e.
        # excluding rows admitted only because they are sticky). `None` means
        # "filter is empty, every tag matches naturally". Used by `lessThan`
        # to pin sticky-only rows below naturally-matching rows.
        self._naturally_matching: set[str] | None = None

    # Setting a sort role results in lots of calls to `data()` and is very
    # slow, so implement a custom `lessThan()` method instead.
    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        left_tag, left_count = self.tag_counter_model.most_common_tags[
            left.row()]
        right_tag, right_count = self.tag_counter_model.most_common_tags[
            right.row()]
        if self._naturally_matching is not None:
            left_natural = left_tag in self._naturally_matching
            right_natural = right_tag in self._naturally_matching
            if left_natural != right_natural:
                # Pin sticky-only rows at the visual bottom of the list
                # regardless of the secondary sort's direction. Qt inverts
                # lessThan under DescendingOrder, so we flip the return so
                # that the visual order is the same in either direction.
                is_ascending = (self.sortOrder()
                                == Qt.SortOrder.AscendingOrder)
                return left_natural if is_ascending else right_natural
        if self.sort_by == AllTagsSortBy.FREQUENCY:
            return left_count < right_count
        elif self.sort_by == AllTagsSortBy.NAME:
            return left_tag < right_tag
        elif self.sort_by == AllTagsSortBy.LENGTH:
            return len(left_tag) < len(right_tag)

    def invalidate(self):
        self._co_cache = {}
        self._refresh_naturally_matching()
        super().invalidate()

    def _refresh_naturally_matching(self):
        if self.filter is None or self.filter == '':
            self._naturally_matching = None
            return
        self._naturally_matching = {
            tag for tag, count in self.tag_counter_model.most_common_tags
            if self._matches(tag, count, self.filter)
        }

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex):
        tag, count = self.tag_counter_model.most_common_tags[source_row]
        if tag in self.sticky_tags:
            return True
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
            if filter_[0] == 'co':
                return self._co_match(tag, filter_[1])
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

    def _co_match(self, tag: str, glob: str) -> bool:
        target_images = self._co_cache.get(glob)
        if target_images is None:
            target_images = set()
            for other_tag, image_indices in (
                    self.tag_counter_model.tag_to_image_indices.items()):
                if fnmatchcase(other_tag, glob):
                    target_images |= image_indices
            self._co_cache[glob] = target_images
        if not target_images:
            return False
        this_images = self.tag_counter_model.tag_to_image_indices.get(
            tag, set())
        return bool(this_images & target_images)
