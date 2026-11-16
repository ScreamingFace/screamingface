export const slugify = (text: string) =>
  text
    .toLowerCase()
    .trim()
    .replace(/[^\w\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')

export interface HeadingInput {
  text: string
  /** An id the author set; it is kept as is. */
  id?: string
}

/**
 * Pairs each heading of one page, in document order, with its id. An author id is kept;
 * any other heading gets the slug of its text, with `-2`, `-3` suffixes against the ids
 * already used on the page and against `taken` (the ids that exist outside the headings).
 */
export const assignHeadingIds = <T extends HeadingInput>(
  headings: T[],
  taken: (id: string) => boolean = () => false,
): Array<{ heading: T; id: string }> => {
  const used = new Set<string>()
  return headings.map((heading) => {
    let id = heading.id ?? ''
    if (!id) {
      const base = slugify(heading.text) || 'section'
      id = base
      let n = 2
      while (used.has(id) || taken(id)) id = `${base}-${n++}`
    }
    used.add(id)
    return { heading, id }
  })
}
