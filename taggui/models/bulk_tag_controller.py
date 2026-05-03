"""Wrapper layer over ``ImageListModel`` for audit-window bulk edits.

The existing model exposes ``add_tags`` (explicit indices) and
``rename_tags`` / ``delete_tags`` (Scope-based, reading from the main
window's selection model). The audit window has its own selection that we
do not want to bleed into the main window, so this controller provides
explicit-index variants of rename and delete that mirror the model's logic
without going through ``Scope.SELECTED_IMAGES``.

This is also a single seam for audit-action logging and (later) batched
undo grouping or dry-run support.
"""
from loguru import logger
from PySide6.QtCore import QObject, Signal

from taggui.models.image_list_model import ImageListModel
from taggui.utils.utils import pluralize


class BulkTagController(QObject):
    operation_completed = Signal(str, int)

    def __init__(self, image_list_model: ImageListModel):
        super().__init__()
        self.image_list_model = image_list_model

    def add_tag(self, tag: str, source_indices: list[int]) -> None:
        if not tag or not source_indices:
            return
        logger.info('Audit: adding tag "{}" to {} images',
                    tag, len(source_indices))
        model_indices = [self.image_list_model.index(i)
                         for i in source_indices]
        self.image_list_model.add_tags([tag], model_indices)
        self.operation_completed.emit('Add tag', len(source_indices))

    def delete_tags_from_images(self, tags: list[str],
                                source_indices: list[int]) -> None:
        if not tags or not source_indices:
            return
        logger.info('Audit: deleting {} from {} images',
                    tags, len(source_indices))
        self.image_list_model.add_to_undo_stack(
            action_name=f'Delete {pluralize("Tag", len(tags))} '
                        f'from Selection',
            should_ask_for_confirmation=True)
        target_set = set(tags)
        changed = self._mutate(
            source_indices,
            lambda image_tags: (
                [t for t in image_tags if t not in target_set]
                if any(t in target_set for t in image_tags)
                else None))
        self._emit_changed(changed)
        self.operation_completed.emit('Delete tags', len(changed))

    def merge_tags(self, source_tags: list[str], target_tag: str,
                   source_indices: list[int]) -> None:
        if not source_tags or not target_tag or not source_indices:
            return
        logger.info('Audit: merging {} → "{}" in {} images',
                    source_tags, target_tag, len(source_indices))
        self.image_list_model.add_to_undo_stack(
            action_name=f'Merge {pluralize("Tag", len(source_tags))}',
            should_ask_for_confirmation=True)
        source_set = set(source_tags)
        changed = self._mutate(
            source_indices,
            lambda image_tags: (
                [target_tag if t in source_set else t for t in image_tags]
                if any(t in source_set for t in image_tags)
                else None))
        self._emit_changed(changed)
        self.operation_completed.emit('Merge tags', len(changed))

    def _mutate(self, source_indices: list[int], transform) -> list[int]:
        """Apply ``transform`` to each image's tag list. The transform
        returns the new tag list, or ``None`` to skip an unchanged image.
        Returns the list of source-row indices that actually changed."""
        changed: list[int] = []
        for source_row in source_indices:
            image = self.image_list_model.images[source_row]
            new_tags = transform(image.tags)
            if new_tags is None:
                continue
            image.tags = new_tags
            self.image_list_model.write_image_tags_to_disk(image)
            changed.append(source_row)
        return changed

    def _emit_changed(self, changed_rows: list[int]) -> None:
        if not changed_rows:
            return
        self.image_list_model.dataChanged.emit(
            self.image_list_model.index(min(changed_rows)),
            self.image_list_model.index(max(changed_rows)))
