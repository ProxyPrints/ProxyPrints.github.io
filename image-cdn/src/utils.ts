export const assertUnreachable = (x: never): never => {
  throw new Error(`Didn't expect to get here with ${x}`);
};

export const MAX_RATE_LIMIT_RETRIES = 5;

export const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

// Same shape as GoogleDriveService.executeCall's retry/backoff (Cloudflare limiter check, plus a
// defensive retry on an upstream 429 - "ideally this case is caught by cloudflare rate limiting
// for us" per that method's own comment), extracted as a standalone helper because this call
// site is a plain unauthenticated GET to a DIFFERENT Google domain (lh4.googleusercontent.com,
// the image-serving CDN) - not the Drive API executeCall is built around (POST, OAuth, JSON/batch
// bodies) - so reusing that method directly would be a worse fit than a small shared primitive.
export const fetchWithRateLimit = async (limiter: RateLimit, key: string, url: string): Promise<Response> => {
  for (let attempt = 0; attempt <= MAX_RATE_LIMIT_RETRIES; attempt++) {
    const { success } = await limiter.limit({ key });
    const backoff = 2 ** attempt + 1000 * Math.random();

    if (success) {
      const response = await fetch(url);
      if (response.status === 429 && attempt < MAX_RATE_LIMIT_RETRIES) {
        await delay(backoff);
        continue;
      }
      return response;
    }

    await delay(backoff);
  }

  throw new Error(`Rate limit exceeded for key "${key}" after ${MAX_RATE_LIMIT_RETRIES} retries`);
};
