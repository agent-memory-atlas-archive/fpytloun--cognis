/** Cache projection only: this does not authenticate network requests. */
export class MediaScopes {
  private clients = new Map<string, { owner: string; epoch: string }>();
  bind(client: string, owner: unknown, epoch: unknown): void {
    if (typeof owner !== 'string' || owner.length > 4096 || typeof epoch !== 'string' || epoch.length > 256) return;
    this.clients.set(client, { owner, epoch });
  }
  revoke(): void { this.clients.clear(); }
  scope(client: string) { return this.clients.get(client); }
  current(client: string, scope: { owner: string; epoch: string }): boolean {
    const now = this.clients.get(client);
    return now?.owner === scope.owner && now.epoch === scope.epoch;
  }
  cache(scope: { owner: string; epoch: string }): string {
    return `cognis-media-account-v2:${encodeURIComponent(scope.owner)}:${encodeURIComponent(scope.epoch)}`;
  }
}
