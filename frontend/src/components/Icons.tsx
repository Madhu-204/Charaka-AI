import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function base(props: IconProps) {
  return {
    width: 18,
    height: 18,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    ...props,
  };
}

export function IconLeaf(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 21C7 16 6 9 11 4c6-4 9-2 10 9 1 8-3 11-9 8Z" />
      <path d="M12 21C12 15 12 9 12 4" />
      <path d="M15 5s2 1 3 3" />
    </svg>
  );
}

export function IconPlant(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 21v-8" />
      <path d="M12 12c0-4 3-7 8-7 0 5-3 8-8 8Z" />
      <path d="M12 11c0-3-2-5-6-5 0 4 2 6 6 6Z" />
    </svg>
  );
}

export function IconChat(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M21 15a4 4 0 0 1-4 4H8l-4 3v-3H7a4 4 0 0 1-4-4V6a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4v9Z" />
      <path d="M8 9h8" />
      <path d="M8 13h5" />
    </svg>
  );
}

export function IconBook(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" />
    </svg>
  );
}

export function IconBookmark(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M19 21l-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16Z" />
    </svg>
  );
}

export function IconBookmarkFilled(props: IconProps) {
  return (
    <svg width={18} height={18} viewBox="0 0 24 24" fill="currentColor" {...props}>
      <path d="M19 21l-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16Z" />
    </svg>
  );
}

export function IconInfo(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="10" />
      <path d="M12 16v-4" />
      <path d="M12 8h.01" />
    </svg>
  );
}

export function IconSend(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M22 2 11 13" />
      <path d="M22 2 15 22l-4-9-9-4 20-7Z" />
    </svg>
  );
}

export function IconChevronDown(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

export function IconChevronLeft(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="m15 18-6-6 6-6" />
    </svg>
  );
}

export function IconChevronRight(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="m9 18 6-6-6-6" />
    </svg>
  );
}

export function IconSearch(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  );
}

export function IconThumbUp(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M7 10v11H4a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1h3Z" />
      <path d="M7 10l4-8a2 2 0 0 1 2 2v5h5.3a2 2 0 0 1 2 2.4l-1.3 6a2 2 0 0 1-2 1.6H7" />
    </svg>
  );
}

export function IconThumbDown(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M17 14V3h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-3Z" />
      <path d="M17 14l-4 8a2 2 0 0 1-2-2v-5H5.7a2 2 0 0 1-2-2.4l1.3-6a2 2 0 0 1 2-1.6H17" />
    </svg>
  );
}

export function IconShield(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  );
}

export function IconScroll(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M8 21h12a2 2 0 0 0 2-2v-2H10v2a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v3h4" />
      <path d="M19 17V5a2 2 0 0 0-2-2H4" />
      <path d="M7 7h6" />
    </svg>
  );
}

export function IconFlow(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="3" y="3" width="6" height="6" rx="1.5" />
      <rect x="15" y="15" width="6" height="6" rx="1.5" />
      <path d="M9 6h4a2 2 0 0 1 2 2v8a2 2 0 0 0 2 2h-2" />
    </svg>
  );
}

export function IconPeople(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20a6.5 6.5 0 0 1 13 0" />
      <path d="M16 3.5a3.5 3.5 0 0 1 0 6.6" />
      <path d="M17 14.5a6.5 6.5 0 0 1 4.5 5.5" />
    </svg>
  );
}

export function IconCheck(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="m4 12 6 6L20 6" />
    </svg>
  );
}

export function IconDatabase(props: IconProps) {
  return (
    <svg {...base(props)}>
      <ellipse cx="12" cy="5" rx="8" ry="3" />
      <path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
      <path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
    </svg>
  );
}

export function IconClock(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </svg>
  );
}

export function IconMenu(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M3 6h18" />
      <path d="M3 12h18" />
      <path d="M3 18h18" />
    </svg>
  );
}

export function IconAlert(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
    </svg>
  );
}