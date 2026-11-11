import { useRef, useState } from 'react';

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
    element?.scrollTo({ top: element.scrollHeight, behavior: 'smooth' });
    markAtBottom();
  }

  return { atBottom, markAtBottom, onScroll, scrollRef, scrollToBottom };
}
