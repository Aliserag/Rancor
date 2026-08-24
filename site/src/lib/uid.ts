// Per-render monotonic counter so repeated <Term> uses on a page get unique
// ids (aria-describedby must resolve to exactly one tooltip; H5).
let n = 0;
export function uid(prefix: string): string {
  n += 1;
  return `${prefix}-${n}`;
}
