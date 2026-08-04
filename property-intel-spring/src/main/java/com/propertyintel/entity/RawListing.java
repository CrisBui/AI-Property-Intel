package com.propertyintel.entity;

import jakarta.persistence.*;
import lombok.*;
import lombok.experimental.FieldDefaults;

@Entity
@Table(name = "raw_listings")
@Builder
@Data
@NoArgsConstructor
@AllArgsConstructor
@FieldDefaults(level = AccessLevel.PRIVATE)
public class RawListing {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    Integer id;

    @Column(name = "source_id", length = 128, nullable = false)
    String sourceId;

    @Column(name = "body", columnDefinition = "Text", nullable = false)
    String body;

    @Column(name = "source_platform", length = 32, nullable = false)
    String sourcePlatform;


}
