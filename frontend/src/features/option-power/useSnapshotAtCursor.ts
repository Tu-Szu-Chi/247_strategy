import { useCallback, useEffect, useRef } from "react";
import { getLiveSnapshotAt, getReplaySnapshotAt } from "./api";
import type { OptionPowerSnapshot } from "./types";

type UseSnapshotAtCursorArgs = {
  enabled: boolean;
  mode: "live" | "replay";
  replaySessionId: string | null;
  onSnapshot: (snapshot: OptionPowerSnapshot) => void;
  onCursorTime: (value: string) => void;
};

const DEBOUNCE_MS = 120;

export function useSnapshotAtCursor({
  enabled,
  mode,
  replaySessionId,
  onSnapshot,
  onCursorTime,
}: UseSnapshotAtCursorArgs) {
  const timeoutRef = useRef<number | null>(null);
  const requestIdRef = useRef(0);

  useEffect(() => {
    return () => {
      if (timeoutRef.current !== null) {
        window.clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  return useCallback((ts: string | null) => {
    if (!enabled || !ts) {
      return;
    }
    onCursorTime(ts);
    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current);
    }
    timeoutRef.current = window.setTimeout(() => {
      requestIdRef.current += 1;
      const requestId = requestIdRef.current;
      const loader = mode === "replay" && replaySessionId
        ? getReplaySnapshotAt(replaySessionId, ts)
        : getLiveSnapshotAt(ts);
      void loader.then((payload) => {
        if (requestId !== requestIdRef.current) {
          return;
        }
        onSnapshot(payload.snapshot);
      }).catch(() => {
        return;
      });
    }, DEBOUNCE_MS);
  }, [enabled, mode, onCursorTime, onSnapshot, replaySessionId]);
}
