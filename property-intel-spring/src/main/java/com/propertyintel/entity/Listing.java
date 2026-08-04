package com.propertyintel.entity;

import jakarta.persistence.*;
import lombok.*;
import lombok.experimental.FieldDefaults;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.LocalDateTime;

@Entity
@Table(name = "listings")
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
@FieldDefaults(level = AccessLevel.PRIVATE)
public class Listing {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    Integer id;

    @Column(name = "source_id", unique = true, length = 128, nullable = false)
    String sourceId;

    @Column(name = "title", length = 512, nullable = false)
    String title;
    @Column(name = "description_raw", columnDefinition = "Text", nullable = false)
    String descriptionRaw;

    @Column(name = "price_vnd")
    Long priceVnd;

    @Column(name = "area_m2")
    Float areaM2;

    @Column(name = "area_min_m2")
    Float areMinM2;

    @Column(name = "area_max_m2")
    Float areMaxM2;

    @Column(name = "district", length = 128)
    String district;

    @Column(name = "address_text", length = 512)
    String addressText;

    Float lat, lng;

    @Column(name = "source_url", length = 1024)
    String sourceUrl;

    @Column(name = "contact_phone", length = 32)
    String contactPhone;

    @Column(name = "short_description", columnDefinition = "Text")
    String shortDescription;

    @Column(name = "description_long", columnDefinition = "TEXT")
    String longDescription;

    @Column(name = "price_note")
    String price_note;

    @Column(name = "sentiment_notes", columnDefinition = "Text")
    String sentimentNotes;

    @Column(name = "extract_confidence")
    @Builder.Default
    Float extractConfidence = 0.0f;

    @Column(name = "posted_at")
    LocalDateTime postedAt;
    @Column(name = "indexed_at")
    private LocalDateTime indexed_at;

    // --- Các trường JSONB map trực tiếp dạng String (lưu chuỗi JSON) qua Hibernate ---
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "amenities_json", columnDefinition = "jsonb")
    private String amenitiesJson;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "near_landmarks_json", columnDefinition = "jsonb")
    private String nearLandmarksJson;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "common_amenities_json", columnDefinition = "jsonb")
    private String commonAmenitiesJson;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "room_layout_tags_json", columnDefinition = "jsonb")
    private String roomLayoutTagsJson;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "service_fees_json", columnDefinition = "jsonb")
    private String serviceFeesJson;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "building_json", columnDefinition = "jsonb")
    private String buildingJson;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "images_json", columnDefinition = "jsonb")
    private String imagesJson; // Bổ sung theo migration 005[cite: 2]
}


