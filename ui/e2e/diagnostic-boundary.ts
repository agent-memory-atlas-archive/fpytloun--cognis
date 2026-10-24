/** Test deadlines fail at a named boundary, never release a gate as success. */
export async function bounded<T>(name: string, work: Promise<T>, milliseconds = 10_000): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      work,
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => reject(new Error(`Fixture boundary timed out: ${name}`)), milliseconds);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

export async function cleanupIndependently(actions: Array<() => Promise<void>>): Promise<unknown[]> {
  const errors: unknown[] = [];
  for (const action of actions) {
    try { await bounded('independent cleanup', action(), 5_000); }
    catch (error) { errors.push(error); }
  }
  return errors;
}
