"""Source model for tags localized to a multi-image selection.

Mirrors ``TagCounterModel`` conventions: ``QAbstractListModel`` over a list of
``(tag, count_in_selection, is_intersection)`` triples that gets recomputed
when the audit window's image selection changes. All set operations run
against the in-memory ``Image.tags`` lists, so there is no extra index to
maintain — the recompute walks only the selected images.
"""
from collections import Counter

from PySide6.QtCore import QAbstractListModel, Qt, Slot

from taggui.models.image_list_model import ImageListModel


class SelectionTagsModel(QAbstractListModel):
    IS_INTERSECTION_ROLE = Qt.ItemDataRole.UserRole + 1
    SELECTION_COUNT_ROLE = Qt.ItemDataRole.UserRole + 2
    SELECTION_SIZE_ROLE = Qt.ItemDataRole.UserRole + 3

    def __init__(self, image_list_model: ImageListModel):
        super().__init__()
        self.image_list_model = image_list_model
        self.entries: list[tuple[str, int, bool]] = []
        self.selection_size: int = 0

    def rowCount(self, parent=None) -> int:
        return len(self.entries)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        tag, count, is_intersection = self.entries[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return f'{tag} ({count}/{self.selection_size})'
        if role == Qt.ItemDataRole.EditRole:
            return tag
        if role == Qt.ItemDataRole.UserRole:
            return tag, count
        if role == self.IS_INTERSECTION_ROLE:
            return is_intersection
        if role == self.SELECTION_COUNT_ROLE:
            return count
        if role == self.SELECTION_SIZE_ROLE:
            return self.selection_size
        return None

    def flags(self, index) -> Qt.ItemFlag:
        return (Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEnabled)

    @Slot(list)
    def recompute(self, selected_image_indices: list[int]):
        """Rebuild the entries list from the given source-model row indices.

        ``selected_image_indices`` are integer rows into
        ``ImageListModel.images`` (i.e., already mapped through any proxy).
        """
        self.beginResetModel()
        try:
            self.selection_size = len(selected_image_indices)
            if not selected_image_indices:
                self.entries = []
                return
            tag_sets = [set(self.image_list_model.images[i].tags)
                        for i in selected_image_indices]
            intersection = set.intersection(*tag_sets)
            counts = Counter(tag for tags in tag_sets for tag in tags)
            self.entries = sorted(
                ((tag, counts[tag], tag in intersection)
                 for tag in counts),
                key=lambda entry: (-entry[1], entry[0]))
        finally:
            self.endResetModel()
