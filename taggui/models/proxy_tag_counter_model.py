import operator
from fnmatch import fnmatchcase

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel

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

    # Setting a sort role results in lots of calls to `data()` and is very
    # slow, so implement a custom `lessThan()` method instead.
    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        left_tag, left_count = self.tag_counter_model.most_common_tags[
            left.row()]
        right_tag, right_count = self.tag_counter_model.most_common_tags[
            right.row()]
        if self.sort_by == AllTagsSortBy.FREQUENCY:
            return left_count < right_count
        elif self.sort_by == AllTagsSortBy.NAME:
            return left_tag < right_tag
        elif self.sort_by == AllTagsSortBy.LENGTH:
            return len(left_tag) < len(right_tag)

    def invalidate(self):
        self._co_cache = {}
        super().invalidate()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex):
        if self.filter is None or self.filter == '':
            return True
        tag, count = self.tag_counter_model.most_common_tags[source_row]
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
