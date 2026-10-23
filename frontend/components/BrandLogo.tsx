import Image from "next/image";

/** The logo mark plus the "Resume Tailor" wordmark. The wordmark is live text so
 *  it stays readable in dark mode (the logo file's navy lettering wouldn't). */
export function BrandLogo({ size = 28 }: { size?: number }) {
  return (
    <span className="flex items-center gap-2">
      <Image src="/brand/mark-96.png" alt="" width={size} height={size} priority />
      <span>
        Resume <span className="text-brand">Tailor</span>
      </span>
    </span>
  );
}
