export type TmdbImageSize = 'w45' | 'w92' | 'w154' | 'w185' | 'w300' | 'w500';

export function tmdbImage(
  path: string | null | undefined,
  size: TmdbImageSize = 'w185',
): string | null {
  if (!path) return null;
  return `https://image.tmdb.org/t/p/${size}${path}`;
}
