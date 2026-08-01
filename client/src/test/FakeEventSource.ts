/**
 * ============================================================================
 * FILE: FakeEventSource.ts
 * LOCATION: client/src/test/FakeEventSource.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Deterministic native EventSource test double.
 *
 * ROLE IN PROJECT:
 *    Lets SSE hook tests emit named events without a real server.
 *
 * KEY COMPONENTS:
 *    - FakeEventSource: Constructor URL, listeners, emit, close
 *
 * DEPENDENCIES:
 *    - External: None
 *    - Internal: None
 *
 * USAGE:
 *    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;
 * ============================================================================
 */

type Listener = (event: MessageEvent) => void;

export class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;

  readonly url: string;
  readyState = FakeEventSource.CONNECTING;
  onerror: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onopen: ((ev: Event) => void) | null = null;

  private listeners = new Map<string, Set<Listener>>();
  closed = false;

  constructor(url: string | URL) {
    this.url = String(url);
    FakeEventSource.instances.push(this);
    queueMicrotask(() => {
      if (!this.closed) {
        this.readyState = FakeEventSource.OPEN;
        this.onopen?.(new Event('open'));
      }
    });
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    const fn =
      typeof listener === 'function'
        ? (listener as Listener)
        : (listener as EventListenerObject).handleEvent.bind(listener);
    const set = this.listeners.get(type) ?? new Set();
    set.add(fn as Listener);
    this.listeners.set(type, set);
  }

  removeEventListener(
    type: string,
    listener: EventListenerOrEventListenerObject,
  ): void {
    const set = this.listeners.get(type);
    if (!set) return;
    const fn =
      typeof listener === 'function'
        ? (listener as Listener)
        : (listener as EventListenerObject).handleEvent.bind(listener);
    set.delete(fn as Listener);
  }

  close(): void {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }

  emit(type: string, data: unknown, lastEventId?: string): void {
    const event = new MessageEvent(type, {
      data: typeof data === 'string' ? data : JSON.stringify(data),
      lastEventId: lastEventId ?? '',
    });
    const set = this.listeners.get(type);
    if (set) {
      for (const listener of set) {
        listener(event);
      }
    }
    if (type === 'message' && this.onmessage) {
      this.onmessage(event);
    }
    if (type === 'error' && this.onerror) {
      this.onerror(new Event('error'));
    }
  }

  static reset(): void {
    FakeEventSource.instances = [];
  }
}
