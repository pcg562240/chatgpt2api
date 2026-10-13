export const BUILTIN_WEB_IMAGE_MODELS = ["gpt-image-2.5-flare", "gpt-image-2.5-sunburst"];

export function imageModelLabel(model: string) {
  if (model === "gpt-image-2.5-flare") return "GPT-Image-2.5 Flare（内置）";
  if (model === "gpt-image-2.5-sunburst") return "GPT-Image-2.5 Sunburst（内置）";
  return model;
}
