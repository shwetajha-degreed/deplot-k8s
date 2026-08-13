import { cn } from "@/lib/cn";
import { ButtonHTMLAttributes, forwardRef } from "react";

type Variant = "primary" | "secondary" | "ghost";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", loading, children, disabled, ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          "relative inline-flex items-center justify-center gap-2 rounded-xl px-5 py-2.5 text-sm font-medium transition-all disabled:cursor-not-allowed disabled:opacity-50 enabled:hover:scale-[1.02] enabled:active:scale-[0.98]",
          variant === "primary" &&
            "bg-gradient-to-r from-indigo-500 via-violet-500 to-indigo-600 text-white shadow-lg shadow-indigo-500/25 hover:shadow-indigo-500/40",
          variant === "secondary" &&
            "border border-white/10 bg-white/5 text-zinc-200 hover:border-indigo-500/30 hover:bg-white/10",
          variant === "ghost" && "text-zinc-400 hover:bg-white/5 hover:text-zinc-200",
          className,
        )}
        disabled={disabled || loading}
        {...props}
      >
        {loading && (
          <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
        )}
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";
