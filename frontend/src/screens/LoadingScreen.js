import React, { useEffect, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Animated,
  Easing,
  Dimensions,
} from 'react-native';

const { width } = Dimensions.get('window');

export default function LoadingScreen({ onFinish }) {
  const logoScale = useRef(new Animated.Value(0)).current;
  const logoOpacity = useRef(new Animated.Value(0)).current;
  const textOpacity = useRef(new Animated.Value(0)).current;
  const barWidth = useRef(new Animated.Value(0)).current;
  const dotOpacity1 = useRef(new Animated.Value(0.3)).current;
  const dotOpacity2 = useRef(new Animated.Value(0.3)).current;
  const dotOpacity3 = useRef(new Animated.Value(0.3)).current;
  const spinValue = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    // Spin animation
    const spin = Animated.loop(
      Animated.timing(spinValue, {
        toValue: 1,
        duration: 2000,
        easing: Easing.linear,
        useNativeDriver: true,
      })
    );
    spin.start();

    // Dots pulsing animation
    const pulseDots = Animated.loop(
      Animated.sequence([
        Animated.timing(dotOpacity1, { toValue: 1, duration: 400, useNativeDriver: true }),
        Animated.timing(dotOpacity2, { toValue: 1, duration: 400, useNativeDriver: true }),
        Animated.timing(dotOpacity3, { toValue: 1, duration: 400, useNativeDriver: true }),
        Animated.timing(dotOpacity1, { toValue: 0.3, duration: 200, useNativeDriver: true }),
        Animated.timing(dotOpacity2, { toValue: 0.3, duration: 200, useNativeDriver: true }),
        Animated.timing(dotOpacity3, { toValue: 0.3, duration: 200, useNativeDriver: true }),
      ])
    );
    pulseDots.start();

    // Main sequence
    Animated.sequence([
      // Logo appears with bounce
      Animated.parallel([
        Animated.spring(logoScale, {
          toValue: 1,
          friction: 4,
          tension: 50,
          useNativeDriver: true,
        }),
        Animated.timing(logoOpacity, {
          toValue: 1,
          duration: 800,
          useNativeDriver: true,
        }),
      ]),
      // Text fades in
      Animated.timing(textOpacity, {
        toValue: 1,
        duration: 600,
        useNativeDriver: true,
      }),
      // Progress bar fills
      Animated.timing(barWidth, {
        toValue: 1,
        duration: 2000,
        easing: Easing.bezier(0.25, 0.46, 0.45, 0.94),
        useNativeDriver: false,
      }),
    ]).start(() => {
      spin.stop();
      pulseDots.stop();
      if (onFinish) onFinish();
    });
  }, []);

  const spinInterpolation = spinValue.interpolate({
    inputRange: [0, 1],
    outputRange: ['0deg', '360deg'],
  });

  return (
    <View style={styles.container}>
      {/* Animated spinning ring behind logo */}
      <Animated.View
        style={[
          styles.spinRing,
          {
            opacity: logoOpacity,
            transform: [{ rotate: spinInterpolation }, { scale: logoScale }],
          },
        ]}
      />

      {/* Logo */}
      <Animated.View
        style={[
          styles.logoContainer,
          {
            opacity: logoOpacity,
            transform: [{ scale: logoScale }],
          },
        ]}
      >
        <View style={styles.logoInner}>
          <Text style={styles.logoText}>M</Text>
        </View>
      </Animated.View>

      {/* App name */}
      <Animated.Text style={[styles.appName, { opacity: textOpacity }]}>
        MyApp
      </Animated.Text>

      {/* Tagline with animated dots */}
      <Animated.View style={[styles.taglineRow, { opacity: textOpacity }]}>
        <Text style={styles.tagline}>Loading</Text>
        <Animated.Text style={[styles.dot, { opacity: dotOpacity1 }]}>.</Animated.Text>
        <Animated.Text style={[styles.dot, { opacity: dotOpacity2 }]}>.</Animated.Text>
        <Animated.Text style={[styles.dot, { opacity: dotOpacity3 }]}>.</Animated.Text>
      </Animated.View>

      {/* Progress bar */}
      <View style={styles.progressBarContainer}>
        <Animated.View
          style={[
            styles.progressBar,
            {
              width: barWidth.interpolate({
                inputRange: [0, 1],
                outputRange: ['0%', '100%'],
              }),
            },
          ]}
        />
      </View>

      {/* Floating particles */}
      <FloatingParticle delay={0} startX={50} startY={200} />
      <FloatingParticle delay={500} startX={width - 80} startY={350} />
      <FloatingParticle delay={1000} startX={100} startY={500} />
      <FloatingParticle delay={300} startX={width - 120} startY={150} />
    </View>
  );
}

function FloatingParticle({ delay, startX, startY }) {
  const opacity = useRef(new Animated.Value(0)).current;
  const translateY = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const anim = Animated.loop(
      Animated.sequence([
        Animated.delay(delay),
        Animated.parallel([
          Animated.sequence([
            Animated.timing(opacity, { toValue: 0.6, duration: 1000, useNativeDriver: true }),
            Animated.timing(opacity, { toValue: 0, duration: 1000, useNativeDriver: true }),
          ]),
          Animated.timing(translateY, {
            toValue: -60,
            duration: 2000,
            useNativeDriver: true,
          }),
        ]),
        Animated.timing(translateY, { toValue: 0, duration: 0, useNativeDriver: true }),
      ])
    );
    anim.start();
    return () => anim.stop();
  }, []);

  return (
    <Animated.View
      style={[
        styles.particle,
        {
          left: startX,
          top: startY,
          opacity,
          transform: [{ translateY }],
        },
      ]}
    />
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#1a1a2e',
    alignItems: 'center',
    justifyContent: 'center',
  },
  spinRing: {
    position: 'absolute',
    width: 140,
    height: 140,
    borderRadius: 70,
    borderWidth: 3,
    borderColor: 'transparent',
    borderTopColor: '#e94560',
    borderRightColor: '#0f3460',
  },
  logoContainer: {
    marginBottom: 20,
  },
  logoInner: {
    width: 100,
    height: 100,
    borderRadius: 50,
    backgroundColor: '#16213e',
    borderWidth: 3,
    borderColor: '#e94560',
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#e94560',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.5,
    shadowRadius: 20,
    elevation: 10,
  },
  logoText: {
    fontSize: 48,
    fontWeight: 'bold',
    color: '#e94560',
  },
  appName: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#eee',
    letterSpacing: 4,
    marginBottom: 8,
  },
  taglineRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 40,
  },
  tagline: {
    fontSize: 16,
    color: '#aaa',
    letterSpacing: 2,
  },
  dot: {
    fontSize: 16,
    color: '#aaa',
    marginLeft: 2,
  },
  progressBarContainer: {
    width: width * 0.6,
    height: 4,
    backgroundColor: '#16213e',
    borderRadius: 2,
    overflow: 'hidden',
  },
  progressBar: {
    height: '100%',
    backgroundColor: '#e94560',
    borderRadius: 2,
  },
  particle: {
    position: 'absolute',
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#e94560',
  },
});
