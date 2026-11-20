import { useRef, useState } from 'react';
import { chatScrollBehavior } from './chatScrollBehavior.mjs';

export function useChatScroll() {
  const [atBottom, setAtBottom] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  function onScroll() {
    const element = scrollRef.current;
    if (!element) return;
    setAtBottom(element.scrollHeight - element.scrollTop - element.clientHeight < 80);
  }

  function markAtBottom() {
    setAtBottom(true);
  }

  function scrollToBottom() {
    const element = scrollRef.current;
    const behavior = chatScrollBehavior({
      systemReduced: typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
      motionAttr: document.documentElement.dataset.motion,
    });
    element?.scrollTo({ top: element.scrollHeight, behavior });
    markAtBottom();
  }

  return { atBottom, markAtBottom, onScroll, scrollRef, scrollToBottom };
}
