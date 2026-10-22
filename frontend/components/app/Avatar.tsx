/* eslint-disable @next/next/no-img-element -- our own private, already-sized image; next/image adds nothing */
import { initials } from "@/lib/user";

const SIZES = { sm: "h-9 w-9 text-sm", lg: "h-20 w-20 text-2xl" } as const;

/** The user's picture (always our own copy, same origin) or their initials. Decorative:
 * the name or email is always written next to it. */
export function Avatar({ src, name, email, size = "sm" }: {
  src: string | null; name: string | null; email: string; size?: keyof typeof SIZES;
}) {
  return src ? (
    <img src={src} alt="" className={`${SIZES[size]} shrink-0 rounded-full object-cover`} />
  ) : (
    <span aria-hidden="true"
      className={`${SIZES[size]} flex shrink-0 items-center justify-center rounded-full bg-accent-soft font-semibold text-fg`}>
      {initials(name, email)}
    </span>
  );
}
