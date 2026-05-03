import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../providers/auth_provider.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({Key? key}) : super(key: key);

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  bool _isLoading = false;

  Future<void> _handleSignIn() async {
    setState(() => _isLoading = true);
    final user = await ref.read(authServiceProvider).signInWithGoogle();
    if (mounted) {
      setState(() => _isLoading = false);
      if (user == null) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Failed to sign in with Google')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF111114),
      body: Stack(
        children: [
          // Background Gradient
          Positioned.fill(
            child: Container(
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [
                    Color(0xFF1A1A22),
                    Color(0xFF111114),
                  ],
                ),
              ),
            ),
          ),
          // Content
          Center(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 40),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  // Logo/Icon
                  Container(
                    width: 100,
                    height: 100,
                    decoration: BoxDecoration(
                      color: const Color(0xFF2563EB).withOpacity(0.1),
                      shape: BoxShape.circle,
                      border: Border.all(color: const Color(0xFF2563EB).withOpacity(0.5), width: 2),
                    ),
                    child: const Center(
                      child: Icon(Icons.rocket_launch, size: 50, color: Color(0xFF2563EB)),
                    ),
                  ),
                  const SizedBox(height: 40),
                  const Text(
                    'JAVRIS',
                    style: TextStyle(
                      color: Color(0xFFF0F0F2),
                      fontSize: 40,
                      fontWeight: FontWeight.w900,
                      letterSpacing: 10,
                    ),
                  ),
                  const SizedBox(height: 16),
                  const Text(
                    'Your Personal AI Assistant',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      color: Color(0xFF888899),
                      fontSize: 16,
                    ),
                  ),
                  const SizedBox(height: 100),
                  // Google Sign In Button
                  if (_isLoading)
                    const CircularProgressIndicator(color: Color(0xFF2563EB))
                  else
                    ElevatedButton(
                      onPressed: _handleSignIn,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: Colors.white,
                        foregroundColor: Colors.black87,
                        minimumSize: const Size(double.infinity, 56),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
                        elevation: 0,
                      ),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Image.network(
                            'https://img.icons8.com/color/48/000000/google-logo.png',
                            height: 24,
                            width: 24,
                          ),
                          const SizedBox(width: 12),
                          const Text(
                            'Continue with Google',
                            style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                          ),
                        ],
                      ),
                    ),
                  const SizedBox(height: 16),
                  if (!_isLoading)
                    TextButton(
                      onPressed: () async {
                        try {
                          setState(() => _isLoading = true);
                          await ref.read(authServiceProvider).signInAnonymously();
                          if (mounted) setState(() => _isLoading = false);
                        } catch (e) {
                          if (mounted) {
                            setState(() => _isLoading = false);
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(content: Text('Sign in failed: $e')),
                            );
                          }
                        }
                      },
                      child: Text(
                        'Continue as Guest (Dev Mode)',
                        style: TextStyle(color: const Color(0xFF2563EB).withOpacity(0.8), fontWeight: FontWeight.w600),
                      ),
                    ),
                  const SizedBox(height: 24),
                  const Text(
                    'By continuing, you agree to our Terms and Privacy Policy',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Color(0xFF555555), fontSize: 12),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
