import React, { useEffect, useRef } from 'react';
import { View, Text, StyleSheet, Animated } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors } from '../theme';

export default function LoadingScreen({ onFinish }) {
  const opacity = useRef(new Animated.Value(0)).current;
  const progress = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    let finished = false;
    const finish = () => {
      if (!finished) {
        finished = true;
        onFinish();
      }
    };
    const fallback = setTimeout(finish, 1400);
    Animated.sequence([
      Animated.timing(opacity, { toValue: 1, duration: 300, useNativeDriver: true }),
      Animated.timing(progress, { toValue: 1, duration: 700, useNativeDriver: false }),
    ]).start(finish);
    return () => clearTimeout(fallback);
  }, [onFinish, opacity, progress]);
  return <View style={styles.page}><Animated.View style={[styles.content, { opacity }]}><View style={styles.mark}><Ionicons name="layers" size={28} color={colors.primary} /></View><Text style={styles.brand}>QUANTUM SWARM</Text><Text style={styles.copy}>Connecting to the engineering control center</Text><View style={styles.track}><Animated.View style={[styles.fill, { width: progress.interpolate({ inputRange: [0, 1], outputRange: ['0%', '100%'] }) }]} /></View></Animated.View></View>;
}
const styles = StyleSheet.create({ page: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.bg }, content: { alignItems: 'center' }, mark: { width: 58, height: 58, borderRadius: 13, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.primarySoft, borderWidth: 1, borderColor: colors.primary }, brand: { color: colors.text, fontSize: 16, fontWeight: '900', letterSpacing: 1.4, marginTop: 15 }, copy: { color: colors.textMuted, fontSize: 11, marginTop: 7 }, track: { width: 240, height: 3, backgroundColor: colors.border, borderRadius: 2, marginTop: 22, overflow: 'hidden' }, fill: { height: 3, backgroundColor: colors.primary } });
