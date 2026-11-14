"use client";

import * as React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Bot, Shield, AlertCircle, ArrowRight, CheckCircle2 } from "lucide-react";
import { getGoogleLoginUrl } from "@/lib/auth";

function GoogleIcon() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24">
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
      />
    </svg>
  );
}

function LoginForm() {
  const searchParams = useSearchParams();
  const errorParam = searchParams.get("error");

  const getErrorMessage = (code: string | null): string | null => {
    if (!code) return null;
    switch (code) {
      case "invalid_oauth_state":
        return "The login session expired or state was invalid. Please try signing in again.";
      case "state_mismatch":
        return "Security token mismatch detected. For your safety, the login was aborted.";
      case "token_verification_failed":
        return "Failed to verify your identity with Google. Please retry.";
      case "unverified_email":
        return "Your Google email address is not verified. Please verify your email with Google first.";
      case "provisioning_failed":
        return "Failed to initialize your user workspace. Please try again or contact support.";
      case "access_denied":
        return "Access was denied by Google. Please approve the required permissions.";
      default:
        return `Sign in failed: ${code.replace(/_/g, " ")}. Please try again.`;
    }
  };

  const errorMessage = getErrorMessage(errorParam);
  const googleLoginUrl = getGoogleLoginUrl();

  return (
    <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-8 shadow-xl">
      {/* Brand Header */}
      <div className="text-center mb-8">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-blue-600 text-white shadow-md shadow-blue-500/20 mb-4">
          <Bot className="h-7 w-7" />
        </div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">
          Sign in to Orchestrix AI
        </h1>
        <p className="mt-2 text-sm text-slate-500">
          Autonomous multi-agent software engineering mesh
        </p>
      </div>

      {/* Error Alert */}
      {errorMessage && (
        <div className="mb-6 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-xs text-red-800">
          <AlertCircle className="h-4 w-4 shrink-0 text-red-600 mt-0.5" />
          <div className="flex-1 leading-relaxed">
            <span className="font-semibold">Authentication failed: </span>
            {errorMessage}
          </div>
        </div>
      )}

      {/* Google Sign In Action */}
      <div className="space-y-4">
        <a
          href={googleLoginUrl}
          className="flex w-full items-center justify-center gap-3 rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm font-semibold text-slate-700 shadow-xs transition hover:bg-slate-50 hover:border-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 active:scale-[0.99]"
        >
          <GoogleIcon />
          <span>Continue with Google</span>
        </a>

        <div className="relative my-6">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-slate-200" />
          </div>
          <div className="relative flex justify-center text-xs uppercase">
            <span className="bg-white px-3 text-slate-400 font-medium tracking-wider">
              Secure Architecture
            </span>
          </div>
        </div>

        {/* Feature bullets */}
        <div className="space-y-2.5 rounded-xl bg-slate-50 p-4 text-xs text-slate-600 border border-slate-100">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-3.5 w-3.5 text-blue-600 shrink-0" />
            <span>OpenID Connect with PKCE (S256) validation</span>
          </div>
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-3.5 w-3.5 text-blue-600 shrink-0" />
            <span>Automatic personal tenant workspace provisioning</span>
          </div>
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-3.5 w-3.5 text-blue-600 shrink-0" />
            <span>Server-side encrypted opaque session management</span>
          </div>
        </div>
      </div>

      {/* Security Assurance */}
      <div className="mt-8 border-t border-slate-100 pt-6 text-center">
        <div className="flex items-center justify-center gap-1.5 text-xs text-slate-400">
          <Shield className="h-3.5 w-3.5 text-slate-400" />
          <span>Enterprise-grade tenant isolation & session security</span>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <div className="min-h-screen flex flex-col justify-center items-center bg-radial from-slate-50 via-slate-100 to-slate-200 p-4 sm:p-6 lg:p-8">
      <React.Suspense
        fallback={
          <div className="h-96 w-full max-w-md animate-pulse rounded-2xl bg-white/60 p-8 shadow-xl" />
        }
      >
        <LoginForm />
      </React.Suspense>

      <div className="mt-6 text-center text-xs text-slate-500">
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1 hover:text-slate-700 transition"
        >
          <span>Return to Dashboard</span>
          <ArrowRight className="h-3 w-3" />
        </Link>
      </div>
    </div>
  );
}
