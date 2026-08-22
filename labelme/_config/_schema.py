from __future__ import annotations

import dataclasses
from typing import Final
from typing import Literal

from .._ai_models import AI_ASSIST_MODEL_OPTIONS

Group = Literal[
    "Appearance",
    "Files and saving",
    "Drawing and canvas",
    "Continue between images",
    "Label sources",
    "Label behavior",
    "AI assist",
]
Kind = Literal["bool", "enum", "str_list"]


@dataclasses.dataclass(frozen=True)
class Setting:
    key_path: tuple[str, ...]
    group: Group
    label: str
    kind: Kind
    # For "enum": the allowed values. A None entry is a real choice meaning
    # "unset/disabled"; it round-trips to YAML null and the dialog renders it
    # as an explicit "(none)" option, never as the string "None".
    choices: tuple[object, ...] | None = None
    # Display labels paralleling choices; falls back to str(choice) when None.
    choice_labels: tuple[str, ...] | None = None
    # Optional muted caption rendered beneath the control.
    note: str | None = None
    # Marks a feature shipped for early use: renders a "BETA" badge beside the
    # label so users expect rough edges and report issues. Drop when it stabilizes.
    beta: bool = False


SETTINGS: Final[tuple[Setting, ...]] = (
    Setting(
        key_path=("color_theme",),
        group="Appearance",
        label="Color theme",
        kind="enum",
        choices=("system", "light", "dark"),
        choice_labels=("System", "Light", "Dark"),
    ),
    Setting(
        key_path=("auto_save",),
        group="Files and saving",
        label="Save automatically",
        kind="bool",
    ),
    Setting(
        key_path=("with_image_data",),
        group="Files and saving",
        label="Save image data in label file",
        kind="bool",
        note="Embeds the image in the label JSON file.",
    ),
    Setting(
        key_path=("display_label_popup",),
        group="Drawing and canvas",
        label="Show label popup on new shape",
        kind="bool",
    ),
    Setting(
        key_path=("keep_prev",),
        group="Continue between images",
        label="Keep previous annotation",
        kind="bool",
    ),
    Setting(
        key_path=("keep_prev_scale",),
        group="Continue between images",
        label="Keep previous zoom",
        kind="bool",
    ),
    Setting(
        key_path=("keep_prev_brightness_contrast",),
        group="Continue between images",
        label="Keep previous brightness/contrast",
        kind="bool",
    ),
    Setting(
        key_path=("canvas", "fill_drawing"),
        group="Drawing and canvas",
        label="Fill polygon while drawing",
        kind="bool",
    ),
    Setting(
        key_path=("canvas", "allow_out_of_bounds_points"),
        group="Drawing and canvas",
        label="Allow points outside the image boundary",
        kind="bool",
        note=(
            "Let shape points extend beyond the image, e.g. for partially "
            "visible objects."
        ),
        beta=True,
    ),
    Setting(
        key_path=("shape", "show_labels"),
        group="Drawing and canvas",
        label="Show shape labels on canvas",
        kind="bool",
        beta=True,
    ),
    Setting(
        key_path=("labels",),
        group="Label sources",
        label="Predefined labels",
        kind="str_list",
    ),
    Setting(
        key_path=("flags",),
        group="Label sources",
        label="Predefined image flags",
        kind="str_list",
    ),
    Setting(
        key_path=("validate_label",),
        group="Label behavior",
        label="Label validation",
        kind="enum",
        choices=(None, "exact"),
    ),
    Setting(
        key_path=("sort_labels",),
        group="Label behavior",
        label="Sort labels",
        kind="bool",
        note=(
            "Sort the label list alphabetically instead of keeping the provided order."
        ),
    ),
    Setting(
        key_path=("show_label_text_field",),
        group="Label behavior",
        label="Show label text field",
        kind="bool",
    ),
    Setting(
        key_path=("label_completion",),
        group="Label behavior",
        label="Label completion",
        kind="enum",
        choices=("startswith", "contains"),
        choice_labels=("Starts with", "Contains"),
    ),
    Setting(
        key_path=("ai", "default"),
        group="AI assist",
        label="Default model",
        kind="enum",
        choices=tuple(option.display_name for option in AI_ASSIST_MODEL_OPTIONS),
        choice_labels=tuple(option.display_name for option in AI_ASSIST_MODEL_OPTIONS),
    ),
    Setting(
        key_path=("ai", "suppress_existing_shape_matches"),
        group="AI assist",
        label="Suppress existing Shape matches",
        kind="bool",
        note=(
            "When an AI Assist candidate matches an existing Shape, highlight "
            "that Shape instead of creating a new Shape."
        ),
    ),
)
