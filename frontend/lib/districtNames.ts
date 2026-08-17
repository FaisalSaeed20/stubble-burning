export const norm = (s: string) => s.toLowerCase().replace(/\s+/g, '').replace(/district$/, '');

export const getFeatureName = (props: Record<string, any>): string =>
  props?.name ||
  props?.NAME ||
  props?.ADM2_EN ||
  props?.ADM2_NAME ||
  props?.DISTRICT ||
  props?.DIST_NAME ||
  props?.district ||
  props?.name_en ||
  props?.NAME_2 ||
  '';
