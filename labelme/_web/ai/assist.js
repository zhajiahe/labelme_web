import { aiAssist, aiText } from "../api.js";
import { pushHistory } from "../annotation/history.js";
import { $ } from "../dom.js";
import { markDirty, state } from "../store.js";
import { setStatus } from "../canvas/renderer.js";

export async function runAiText({ onChanged } = {}) {
  setStatus("Running AI text prompt…");
  const result = await aiText({
    text: $("ai-text").value,
    output_format: $("ai-text-format").value,
    model_name: $("ai-model").value,
  });
  pushHistory();
  state.shapes.push(...(result.new_shapes || []));
  markDirty();
  onChanged?.();
  setStatus(`Added ${result.new_shapes?.length || 0} shapes`);
}

export async function runAiPoints({ onChanged } = {}) {
  if (!state.aiPoints.length) return;
  setStatus("Running AI Assist…");
  const result = await aiAssist({
    prompt_kind: "points",
    points: state.aiPoints.map((p) => p.xy),
    point_labels: state.aiPoints.map((p) => p.label),
    output_format: "polygon",
    existing_shapes: state.shapes,
    model_name: $("ai-model").value,
  });
  pushHistory();
  state.shapes.push(...(result.new_shapes || []));
  state.aiPoints = [];
  markDirty();
  onChanged?.();
  setStatus(`AI Assist added ${result.new_shapes?.length || 0}`);
}

export async function runAiBox(box, { onChanged } = {}) {
  setStatus("Running AI Assist…");
  const result = await aiAssist({
    prompt_kind: "box",
    points: box.points,
    point_labels: [1, 1],
    output_format: "polygon",
    existing_shapes: state.shapes,
    model_name: $("ai-model").value,
  });
  pushHistory();
  state.shapes.push(...(result.new_shapes || []));
  markDirty();
  onChanged?.();
  setStatus(`AI Assist added ${result.new_shapes?.length || 0}`);
}

export function fillAiModels(session) {
  const model = $("ai-model");
  if (!model.options.length) {
    (session.ai_models || []).forEach((option) => {
      const el = document.createElement("option");
      el.value = option.display_name;
      el.textContent = option.display_name;
      model.appendChild(el);
    });
  }
  model.value = session.config?.ai?.default || model.value;
}
