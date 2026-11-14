import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium transition-colors select-none",
  {
    variants: {
      variant: {
        default:
          "border-blue-200 bg-blue-50 text-blue-700",
        secondary:
          "border-slate-200 bg-slate-100 text-slate-700",
        outline:
          "border-slate-200 bg-white text-slate-700",
        success:
          "border-emerald-200 bg-emerald-50 text-emerald-700",
        warning:
          "border-amber-200 bg-amber-50 text-amber-700",
        destructive:
          "border-rose-200 bg-rose-50 text-rose-700",
        agent:
          "border-blue-100 bg-blue-50/70 text-blue-800 font-mono text-[11px]",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {
  dotColor?: string;
}

function Badge({ className, variant, dotColor, children, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props}>
      {dotColor && (
        <span
          className={cn("h-1.5 w-1.5 rounded-full shrink-0", dotColor)}
          aria-hidden="true"
        />
      )}
      {children}
    </div>
  );
}

export { Badge, badgeVariants };
